"""Write the OpenAPI schema to a file: ``python -m app.export_openapi ../frontend/openapi.json``.

The frontend generates its TypeScript types from this file, so they cannot drift from the API.
"""

import json
import sys
from pathlib import Path

from app.main import create_app


def build() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    target.write_text(build(), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
