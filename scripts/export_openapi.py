"""Write the API's OpenAPI document to frontend/openapi.json (or check that it is current).

The frontend generates its request types from this file (`npm run api:types`). Run from the
repository root with the backend interpreter:

    backend/.venv/Scripts/python.exe scripts/export_openapi.py          # write
    backend/.venv/Scripts/python.exe scripts/export_openapi.py --check  # CI: fail when stale
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

TARGET = ROOT / "frontend" / "openapi.json"


def main():
    from app.main import app

    text = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print("FAIL: frontend/openapi.json is stale; run scripts/export_openapi.py")
            return 1
        print("PASS: frontend/openapi.json matches the API")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"Wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
