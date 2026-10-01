"""Keeps docs/prd-traceability.md honest: every cited path, symbol and test must exist."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "prd-traceability.md"
STATUSES = ("✅", "🟡", "⏳", "🚫")
ROW = re.compile(r"^\| (R\d+\.\d+) \|")
REF = re.compile(r"`([^`]+)`")
PATH_PREFIXES = ("packages/", "tests/", "services/", "supabase/", "apps/", ".github/", "docs/")
ROOT_FILES = {"pyproject.toml", ".env.example", "Makefile", "README.md", "CLAUDE.md"}


def _rows() -> list[tuple[str, str, list[str]]]:
    rows = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        assert len(cells) == 6, f"{m.group(1)}: expected 6 columns, got {len(cells)}"
        status = next((s for s in STATUSES if cells[2].startswith(s)), None)
        assert status, f"{m.group(1)}: unknown status {cells[2]!r}"
        rows.append((m.group(1), status, REF.findall(line)))
    return rows


def _is_path_ref(ref: str) -> bool:
    head = ref.split("::")[0]
    return " " not in head and (head.startswith(PATH_PREFIXES) or head in ROOT_FILES)


def summary_counts() -> Counter[str]:
    return Counter(status for _, status, _ in _rows())


def render_summary() -> str:
    """The exact text expected between the summary markers."""
    rows = _rows()
    counts = summary_counts()
    lines = ["| Estado | Requisitos |", "|---|---|"]
    lines += [f"| {s} | {counts.get(s, 0)} |" for s in STATUSES]
    lines.append(f"| **Total** | **{sum(counts.values())}** |")
    lines += ["", "| Sección | " + " | ".join(STATUSES) + " | Total |", "|---|---|---|---|---|---|"]
    by_section: dict[int, Counter[str]] = {}
    for rid, status, _ in rows:
        by_section.setdefault(int(rid[1:].split(".")[0]), Counter())[status] += 1
    for sec in sorted(by_section):
        c = by_section[sec]
        cells = " | ".join(str(c.get(s, 0)) for s in STATUSES)
        lines.append(f"| §{sec} | {cells} | {sum(c.values())} |")
    return "\n".join(lines)


def test_ids_unique_and_present() -> None:
    ids = [rid for rid, _, _ in _rows()]
    assert len(ids) > 100
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate IDs: {dupes}"


def test_referenced_paths_symbols_and_tests_exist() -> None:
    errors = []
    for rid, _, refs in _rows():
        for ref in filter(_is_path_ref, refs):
            path_s, _, symbol = ref.partition("::")
            path = ROOT / path_s
            if not path.exists():
                errors.append(f"{rid}: missing path {path_s}")
                continue
            if not symbol:
                continue
            text = path.read_text(encoding="utf-8")
            if path_s.startswith("tests/"):
                if not re.search(rf"^def {re.escape(symbol)}\(", text, re.M):
                    errors.append(f"{rid}: missing test {ref}")
            elif not re.search(rf"\b{re.escape(symbol)}\b", text):
                errors.append(f"{rid}: missing symbol {ref}")
    assert not errors, "\n".join(errors)


def test_summary_matches_rows() -> None:
    text = DOC.read_text(encoding="utf-8")
    block = text.split("<!-- summary:start -->")[1].split("<!-- summary:end -->")[0]
    assert block.strip() == render_summary(), (
        "Summary out of date; regenerate with: uv run python tests/test_traceability.py"
    )


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    # Rewrite the summary block in place.
    text = DOC.read_text(encoding="utf-8")
    head, rest = text.split("<!-- summary:start -->")
    _, tail = rest.split("<!-- summary:end -->")
    DOC.write_text(
        f"{head}<!-- summary:start -->\n{render_summary()}\n<!-- summary:end -->{tail}",
        encoding="utf-8",
    )
    print(render_summary())
