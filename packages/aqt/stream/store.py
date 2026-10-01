"""Local SQLite store for the streaming engine: raw ticks, decisions, orders, trades, equity.

Writes are buffered and committed by :meth:`SQLiteStore.flush` (the runner calls it about once a
second) so a burst of ticks never blocks the event loop on disk I/O. WAL mode lets other
processes read the file while the trader runs.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from aqt.brokers.base import BrokerOrder
from aqt.brokers.paper import Fill
from aqt.stream.events import Event, Quote, TradeTick
from aqt.stream.records import Decision, RoundTrip

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    ts REAL NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL,
    a REAL, b REAL, c REAL, d REAL, flag INTEGER
);
CREATE INDEX IF NOT EXISTS ticks_symbol_ts ON ticks(symbol, ts);
CREATE INDEX IF NOT EXISTS ticks_ts ON ticks(ts);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, ts REAL NOT NULL, symbol TEXT,
    strategy_id TEXT, side TEXT, kind TEXT, action TEXT, quantity REAL, notional REAL,
    reasons TEXT, detail TEXT, checks TEXT
);
CREATE INDEX IF NOT EXISTS decisions_run_ts ON decisions(run_id, ts);
CREATE TABLE IF NOT EXISTS orders (
    run_id TEXT NOT NULL, order_id TEXT NOT NULL, client_order_id TEXT, ts REAL,
    symbol TEXT, side TEXT, quantity REAL, status TEXT, fill_price REAL, fill_ts REAL, fee REAL,
    PRIMARY KEY (run_id, order_id)
);
CREATE TABLE IF NOT EXISTS round_trips (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, book TEXT NOT NULL, strategy_id TEXT,
    symbol TEXT, entry_ts REAL, exit_ts REAL, entry_price REAL, exit_price REAL,
    quantity REAL, pnl REAL, fees REAL, net_return REAL, exit_reason TEXT, context TEXT
);
CREATE INDEX IF NOT EXISTS round_trips_run_book ON round_trips(run_id, book, exit_ts);
CREATE TABLE IF NOT EXISTS equity (
    run_id TEXT NOT NULL, ts REAL NOT NULL, equity REAL, cash REAL, positions_value REAL
);
CREATE INDEX IF NOT EXISTS equity_run_ts ON equity(run_id, ts);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class SQLiteStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        # timeout: the Research Lab writes from another process; wait instead of failing.
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=60)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(round_trips)")}
            if "context" not in cols:  # databases created before meta-labeling
                self._conn.execute("ALTER TABLE round_trips ADD COLUMN context TEXT")
            self._conn.commit()
        self._ticks: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------ lifecycle
    def flush(self) -> None:
        with self._lock:
            if self._ticks:
                self._conn.executemany(
                    "INSERT INTO ticks (ts, symbol, kind, a, b, c, d, flag) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    self._ticks,
                )
                self._ticks = []
            self._conn.commit()

    def close(self) -> None:
        self.flush()
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ ticks
    def record(self, event: Event) -> None:
        row: tuple[Any, ...]
        if isinstance(event, Quote):
            row = (
                event.ts,
                event.symbol,
                "Q",
                event.bid,
                event.bid_qty,
                event.ask,
                event.ask_qty,
                0,
            )
        else:
            row = (
                event.ts,
                event.symbol,
                "T",
                event.price,
                event.qty,
                None,
                None,
                int(event.buyer_is_maker),
            )
        self._ticks.append(row)

    def iter_ticks(
        self,
        symbols: Sequence[str] | None = None,
        start: float | None = None,
        end: float | None = None,
    ) -> Iterator[Event]:
        self.flush()
        sql = "SELECT ts, symbol, kind, a, b, c, d, flag FROM ticks WHERE 1=1"
        args: list[Any] = []
        if symbols:
            sql += f" AND symbol IN ({','.join('?' * len(symbols))})"
            args += list(symbols)
        if start is not None:
            sql += " AND ts >= ?"
            args.append(start)
        if end is not None:
            sql += " AND ts < ?"
            args.append(end)
        sql += " ORDER BY ts, rowid"
        # A dedicated read connection keeps a long replay from holding the writer lock.
        conn = sqlite3.connect(self.path) if self.path != ":memory:" else self._conn
        try:
            for ts, sym, kind, a, b, c, d, flag in conn.execute(sql, args):
                if kind == "Q":
                    yield Quote(sym, ts, a, b, c, d)
                else:
                    yield TradeTick(sym, ts, a, b, bool(flag))
        finally:
            if conn is not self._conn:
                conn.close()

    def tick_summary(self) -> list[dict[str, Any]]:
        self.flush()
        with self._lock:
            rows = self._conn.execute(
                "SELECT symbol, kind, COUNT(*) n, MIN(ts) first, MAX(ts) last "
                "FROM ticks GROUP BY symbol, kind ORDER BY symbol, kind"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ audit
    def log_decision(self, run_id: str, d: Decision) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO decisions (run_id, ts, symbol, strategy_id, side, kind, action, "
                "quantity, notional, reasons, detail, checks) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    d.ts,
                    d.symbol,
                    d.strategy_id,
                    d.side,
                    d.kind,
                    d.action,
                    d.quantity,
                    d.notional,
                    json.dumps(list(d.reasons)),
                    d.detail,
                    json.dumps([list(c) for c in d.checks]),
                ),
            )

    def log_order(self, run_id: str, order: BrokerOrder, ts: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO orders (run_id, order_id, client_order_id, ts, symbol, "
                "side, quantity, status) VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    order.order_id,
                    order.client_order_id,
                    ts,
                    order.symbol,
                    str(order.side),
                    order.quantity,
                    str(order.status),
                ),
            )

    def log_fill(self, run_id: str, fill: Fill) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE orders SET status='FILLED', fill_price=?, fill_ts=?, fee=? "
                "WHERE run_id=? AND order_id=?",
                (fill.price, fill.ts, fill.fee, run_id, fill.order_id),
            )

    def log_round_trip(self, run_id: str, rt: RoundTrip) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO round_trips (run_id, book, strategy_id, symbol, entry_ts, exit_ts, "
                "entry_price, exit_price, quantity, pnl, fees, net_return, exit_reason, context) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    rt.book,
                    rt.strategy_id,
                    rt.symbol,
                    rt.entry_ts,
                    rt.exit_ts,
                    rt.entry_price,
                    rt.exit_price,
                    rt.quantity,
                    rt.pnl,
                    rt.fees,
                    rt.net_return,
                    rt.exit_reason,
                    json.dumps(rt.context) if rt.context else None,
                ),
            )

    def log_equity(
        self, run_id: str, ts: float, equity: float, cash: float, positions_value: float
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO equity (run_id, ts, equity, cash, positions_value) VALUES (?,?,?,?,?)",
                (run_id, ts, equity, cash, positions_value),
            )

    # ------------------------------------------------------------------ queries
    def round_trips(
        self, run_id: str, book: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM round_trips WHERE run_id=?"
        args: list[Any] = [run_id]
        if book:
            sql += " AND book=?"
            args.append(book)
        sql += " ORDER BY exit_ts DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def realized_pnl(self, run_id: str) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM round_trips WHERE run_id=? AND book='paper'",
                (run_id,),
            ).fetchone()
        return float(row[0])

    def shadow_returns(self, run_id: str, limit: int = 500) -> list[tuple[str, float]]:
        """Oldest-first ``(strategy_id, net_return)`` of the last ``limit`` shadow trades."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT strategy_id, net_return FROM (SELECT id, exit_ts, strategy_id, net_return "
                "FROM round_trips WHERE run_id=? AND book='shadow' ORDER BY exit_ts DESC, id DESC "
                "LIMIT ?) ORDER BY exit_ts, id",
                (run_id, limit),
            ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def decisions(self, run_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, symbol, strategy_id, side, kind, action, quantity, notional, reasons, "
                "detail FROM decisions WHERE run_id=? ORDER BY ts DESC, id DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d["reasons"] or "[]")
            out.append(d)
        return out

    def equity_curve(self, run_id: str, since: float | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, equity, cash, positions_value FROM equity WHERE run_id=? AND ts>=? "
                "ORDER BY ts",
                (run_id, since or 0.0),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ generic access
    def execute(self, sql: str, args: Sequence[Any] = (), commit: bool = True) -> int:
        """Run one statement (used by the Research Lab registry); returns lastrowid."""
        with self._lock:
            cur = self._conn.execute(sql, tuple(args))
            if commit:
                self._conn.commit()
            return int(cur.lastrowid or 0)

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)
            self._conn.commit()

    def query(self, sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(args)).fetchall()]

    def strategy_trades(
        self, run_id: str, strategy_id: str, book: str = "shadow"
    ) -> list[tuple[float, dict[str, float]]]:
        """Oldest-first ``(net_return, entry context)`` of trades that recorded a context."""
        rows = self.query(
            "SELECT net_return, context FROM round_trips WHERE run_id=? AND book=? "
            "AND strategy_id=? AND context IS NOT NULL ORDER BY exit_ts, id",
            (run_id, book, strategy_id),
        )
        return [(float(r["net_return"]), json.loads(r["context"])) for r in rows]

    def strategy_returns(self, run_id: str, strategy_id: str, book: str = "shadow") -> list[float]:
        """Oldest-first net returns of one strategy's closed trades in ``book``."""
        rows = self.query(
            "SELECT net_return FROM round_trips WHERE run_id=? AND book=? AND strategy_id=? "
            "ORDER BY exit_ts, id",
            (run_id, book, strategy_id),
        )
        return [float(r["net_return"]) for r in rows]

    # ------------------------------------------------------------------ settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()
