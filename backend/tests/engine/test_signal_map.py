"""docs/signal-map.md must cover every row of the PRD 6장 table with functions that exist."""

import importlib
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[3] / "docs"
USAGE_PREFIXES = ("스크리너", "공통", "매도", "재매수", "강제 매도")


def table_rows(path: Path, section: str = "") -> list[list[str]]:
    """Rows of the signal table. ``section`` limits the PRD to one chapter heading prefix."""
    text = path.read_text(encoding="utf-8")
    if section:
        start = text.index(section)
        text = text[start : text.index("\n## ", start + 1)]
    rows = []
    for line in text.splitlines():
        if line.startswith("| ") and not line.startswith("| ---"):
            cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
            if cells[0].startswith(USAGE_PREFIXES):
                rows.append(cells)
    return rows


PRD_ROWS = [(cells[0], cells[1]) for cells in table_rows(DOCS / "PRD.md", "## 6. 지표와 신호 정의")]
MAP_ROWS = {(cells[0], cells[1]): cells for cells in table_rows(DOCS / "signal-map.md")}


def test_the_prd_table_was_found() -> None:
    assert len(PRD_ROWS) == 31


@pytest.mark.parametrize(("usage", "signal"), PRD_ROWS)
def test_every_prd_row_has_a_function_in_the_map(usage: str, signal: str) -> None:
    assert (usage, signal) in MAP_ROWS, f"{usage} / {signal} is missing from docs/signal-map.md"
    assert re.search(r"`\w+\.\w+`", MAP_ROWS[(usage, signal)][2])


def test_the_map_has_no_rows_that_the_prd_table_lacks() -> None:
    assert set(MAP_ROWS) <= set(PRD_ROWS)


def test_every_function_named_in_the_map_exists() -> None:
    text = (DOCS / "signal-map.md").read_text(encoding="utf-8")
    references = set(re.findall(r"`(\w+)\.(\w+)`", text))

    assert references
    for module_name, attribute in sorted(references):
        module = importlib.import_module(f"app.engine.{module_name}")
        assert hasattr(module, attribute), f"{module_name}.{attribute} does not exist"
