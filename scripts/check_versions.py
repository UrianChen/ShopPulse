"""Check synchronized release versions; API schemas are generated at runtime."""

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import __version__
from app.db import SCHEMA_REVISION


def main():
    version = (ROOT / "VERSION").read_text().strip()
    assert __version__ == version, "API version differs from VERSION"
    for filename in ("package.json", "package-lock.json"):
        data = json.loads((ROOT / "frontend" / filename).read_text())
        assert data["version"] == version, f"{filename} version differs"
        if filename == "package-lock.json":
            assert data["packages"][""]["version"] == version
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())
    assert project["project"]["version"] == version.replace("-rc.", "rc")
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text())
    locked = next(p for p in lock["package"] if p["name"] == "shoppulse-backend")
    assert locked["version"] == project["project"]["version"]
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    migrations = ScriptDirectory.from_config(Config(ROOT / "backend/alembic.ini"))
    assert migrations.get_current_head() == SCHEMA_REVISION, "Database revision differs"
    print(f"PASS: synchronized release versions ({version})")


if __name__ == "__main__":
    main()
