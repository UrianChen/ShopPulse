"""Streaming storage archive; only regular files, no links, no path traversal."""

import json
import sys
import tarfile
from pathlib import Path
from urllib.request import build_opener

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import session as db_module
from app.db.models import DatasetVersion, ModelConfig, Report, Workspace
from app.ingestion.storage import storage_root
from app.providers.credentials import decrypt
from app.reports.tools import digest


def main():
    action = sys.argv[1]
    root = storage_root()
    if action == "pack":
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    elif action == "unpack":
        if any(root.iterdir()):
            raise ValueError("Restore requires empty storage")
        total, count = 0, 0
        with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:
            for entry in archive:
                path = (root / entry.name).resolve()
                if not entry.isfile() or not path.is_relative_to(root) or path == root:
                    raise ValueError("Unsafe archive member")
                count += 1
                total += entry.size
                if count > 250000 or total > 20 * 1024**3:
                    raise ValueError("Archive limit")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as output, archive.extractfile(entry) as source:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
    elif action == "inspect":
        with Session(db_module.engine()) as db:
            models = list(db.scalars(select(ModelConfig)))
            for config in models:
                decrypt(config)  # Fail closed if the separately supplied credential key is wrong.
            reports = list(db.scalars(select(Report).order_by(Report.id)))
            result = {
                "schema_revision": db.scalar(text("SELECT version_num FROM alembic_version")),
                "workspaces": db.scalar(select(func.count()).select_from(Workspace)),
                "datasets": db.scalar(select(func.count()).select_from(DatasetVersion)),
                "reports": len(reports),
                "models": len(models),
                "credentials_readable": True,
                "report_digest": digest([r.content for r in reports]),
            }
            print(json.dumps(result))
    elif action == "verify-data":
        base = "http://127.0.0.1:8000/api/v1"
        opener = build_opener()
        for path in ("/workspace", "/datasets", "/reports"):
            with opener.open(base + path, timeout=15) as response:
                assert response.status == 200
        print("PASS: restored workspace, datasets and reports are readable")
    elif action == "scan-secrets":
        # Keys never leave the backend. The caller sends logs/build artifacts through stdin.
        with Session(db_module.engine()) as db:
            needles = [decrypt(row).encode() for row in db.scalars(select(ModelConfig))]
        cfg = settings()
        needles += [
            cfg.secret(name).encode()
            for name in (
                cfg.credential_master_key_file,
                cfg.database_password_file,
            )
        ]
        needles = [value for value in needles if len(value) >= 12]

        def check(data):
            if any(value in data for value in needles):
                raise SystemExit("FAIL: credential value found; inspect privately")

        check(sys.stdin.buffer.read())
        count = 0
        for directory in (root, Path(__file__).resolve().parents[1]):
            for path in directory.rglob("*"):
                if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
                    check(path.read_bytes())
                    count += 1
        print(
            f"PASS: backend/storage files ({count}) and supplied logs/build "
            "contain no configured secret values"
        )


if __name__ == "__main__":
    main()
