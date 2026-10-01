"""Local dashboard + API (FastAPI). Binds to 127.0.0.1 only.

Read endpoints expose the engine snapshot and the SQLite audit trail. The single write endpoint
(``/api/control``) can only make the system *safer or quieter*: kill switch, pause, flatten and
the aggressiveness slider (always clamped by ``AbsoluteLimits``). It cannot enable LIVE trading,
change limits or send orders. Requests from foreign browser origins are refused.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from services.trader.runtime import TraderRuntime

DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "apps" / "dashboard" / "local"
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


class Control(BaseModel):
    kill_switch: bool | None = None
    paused: bool | None = None
    aggressiveness: float | None = Field(default=None, ge=0, le=100)
    flatten: bool = False
    speed: float | None = Field(default=None, ge=0, le=10_000)  # simulations only


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True  # non-browser clients (curl, tests)
    host = origin.split("://", 1)[-1].split("/", 1)[0]
    host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    return host in _LOCAL_HOSTS


def create_app(runtime: TraderRuntime, push_seconds: float = 0.5) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="Autonomous Quant Trader — local", lifespan=lifespan)
    run_id = runtime.engine.cfg.run_id

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next: Any) -> Any:
        if not _origin_allowed(request.headers.get("origin")):
            return JSONResponse({"detail": "foreign origin"}, status_code=403)
        return await call_next(request)

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return runtime.snapshot()

    @app.get("/api/trades")
    async def trades(book: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if book not in (None, "paper", "shadow"):
            raise HTTPException(400, "book must be paper or shadow")
        return runtime.store.round_trips(run_id, book, min(limit, 2000))

    @app.get("/api/decisions")
    async def decisions(limit: int = 200) -> list[dict[str, Any]]:
        return runtime.store.decisions(run_id, min(limit, 2000))

    @app.get("/api/equity")
    async def equity(since: float | None = None) -> list[dict[str, Any]]:
        return runtime.store.equity_curve(run_id, since)

    @app.post("/api/control")
    async def control(body: Control) -> dict[str, Any]:
        runtime.control(
            kill_switch=body.kill_switch,
            paused=body.paused,
            aggressiveness=body.aggressiveness,
            flatten=body.flatten,
            speed=body.speed,
        )
        e = runtime.engine
        return {
            "kill_switch": e.kill_switch,
            "paused": e.paused,
            "aggressiveness": e.profile.aggressiveness,
        }

    @app.get("/api/research")
    async def research() -> dict[str, Any]:
        if runtime.lab is None:
            return {
                "status": {"enabled": False},
                "hypotheses": [],
                "runs": [],
                "rules": [],
                "events": [],
                "lessons": [],
            }
        return runtime.lab.overview()

    @app.get("/api/hypotheses")
    async def hypotheses() -> list[dict[str, Any]]:
        if runtime.lab is None:
            return []
        hyps: list[dict[str, Any]] = runtime.lab.overview()["hypotheses"]
        return hyps

    @app.get("/api/golive")
    async def golive() -> dict[str, Any]:
        if runtime.golive is None:
            return {"enabled": False}
        return {"enabled": True, **runtime.golive.overview()}

    @app.post("/api/research/run")
    async def research_run() -> dict[str, Any]:
        if runtime.lab is None:
            raise HTTPException(409, "Research Lab not enabled")
        return {"started": runtime.lab.trigger()}

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        if not _origin_allowed(socket.headers.get("origin")):
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            while True:
                await socket.send_json(runtime.snapshot())
                await asyncio.sleep(push_seconds)
        except (WebSocketDisconnect, RuntimeError):
            return

    if DASHBOARD_DIR.is_dir():
        app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
    return app
