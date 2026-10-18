from pathlib import Path

from app.export_openapi import build

COMMITTED = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def test_the_committed_openapi_file_matches_the_api() -> None:
    """If this fails, run `make gen-api` and commit frontend/openapi.json and its types."""
    assert COMMITTED.read_text(encoding="utf-8") == build()
