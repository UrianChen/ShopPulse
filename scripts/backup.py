"""Offline Compose backup; restores only into a new isolated project, never over production."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import SCHEMA_REVISION


def compose(project=None):
    command = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    if project:
        command += ["-f", str(ROOT / ".cache" / "restore-image.json"), "-p", project]
    return command


def call(base, *args, input_file=None, output_file=None):
    with (
        open(input_file, "rb") if input_file else open(os.devnull, "rb") as source,
        open(output_file, "wb") if output_file else open(os.devnull, "wb") as sink,
    ):
        result = subprocess.run(
            base + list(args),
            stdin=source,
            stdout=sink if output_file else subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ROOT,
            check=False,
        )
    if result.returncode:
        raise RuntimeError(
            "Compose operation failed; no credentials or process stderr displayed."
        )
    return result.stdout or b""


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def backup(directory):
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    base = compose()
    running = (
        call(base, "ps", "--services", "--status", "running").decode().splitlines()
    )
    pause = [s for s in ("web", "api", "worker") if s in running]
    try:
        if pause:
            call(base, "stop", *pause)
        snapshot = json.loads(
            call(
                base,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "api",
                "python",
                "-m",
                "app.ops.archive",
                "inspect",
            )
        )
        call(
            base,
            "exec",
            "-T",
            "db",
            "pg_dump",
            "-U",
            "shoppulse",
            "-d",
            "shoppulse",
            "-Fc",
            output_file=directory / "database.dump",
        )
        call(
            base,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "python",
            "-m",
            "app.ops.archive",
            "pack",
            output_file=directory / "storage.tar",
        )
        manifest = {
            "schema": snapshot["schema_revision"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": snapshot,
            "files": {f: sha(directory / f) for f in ("database.dump", "storage.tar")},
            "secrets_included": False,
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    finally:
        if pause:
            call(base, "start", *pause)
    print(
        "Backup complete. Keep database/files private; back up secrets independently."
    )


def restore(directory, project):
    if not re.fullmatch(r"shoppulse-restore-[a-z0-9-]{1,40}", project):
        raise ValueError(
            "Restore project must start with shoppulse-restore- and be new"
        )
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["schema"] != SCHEMA_REVISION:
        raise ValueError("Use the matching application revision before migrating")
    for name in ("database.dump", "storage.tar"):
        if sha(directory / name) != manifest["files"][name]:
            raise ValueError("Backup checksum mismatch")
    # Refuse projects with ANY existing resources, including stopped containers and orphan volumes.
    for resource in ("ps", "volume"):
        command = (
            ["docker", "ps", "-aq"]
            if resource == "ps"
            else ["docker", "volume", "ls", "-q"]
        )
        output = subprocess.check_output(
            command + ["--filter", f"label=com.docker.compose.project={project}"]
        )
        if output.strip():
            raise ValueError("Restore destination already exists")
    # Reuse the exact source image, avoiding an implicit build in binary archive pipelines.
    image = call(compose(), "images", "-q", "api").decode().strip().splitlines()[0]
    override = ROOT / ".cache" / "restore-image.json"
    override.parent.mkdir(exist_ok=True)
    override.write_text(
        json.dumps(
            {
                "services": {
                    service: {"image": image}
                    for service in ("api", "worker", "migrate")
                }
            }
        ),
        encoding="utf-8",
    )
    base = compose(project)
    call(base, "up", "-d", "--wait", "db")
    call(
        base,
        "exec",
        "-T",
        "db",
        "pg_restore",
        "-U",
        "shoppulse",
        "-d",
        "shoppulse",
        "--exit-on-error",
        "--no-owner",
        "--clean",
        "--if-exists",
        input_file=directory / "database.dump",
    )
    call(
        base,
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "api",
        "python",
        "-m",
        "app.ops.archive",
        "unpack",
        input_file=directory / "storage.tar",
    )
    actual = json.loads(
        call(
            base,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "python",
            "-m",
            "app.ops.archive",
            "inspect",
        )
    )
    if actual != manifest["snapshot"]:
        raise ValueError("Restored logical data does not match backup")
    call(base, "up", "-d", "--wait", "api")
    call(
        base,
        "exec",
        "-T",
        "api",
        "python",
        "-m",
        "app.ops.archive",
        "verify-data",
    )
    print(
        "Restore verified: workspaces, datasets, frozen report digest and credential decryption match. "
        "No host ports opened; worker stays stopped until the operator explicitly resumes jobs."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--project")
    args = parser.parse_args()
    try:
        if args.action == "backup":
            backup(args.directory.resolve())
        elif args.project:
            restore(args.directory.resolve(), args.project)
        else:
            parser.error("Restore requires --project")
    except Exception:  # noqa: BLE001 -- never echo subprocess diagnostics that might include secrets
        raise SystemExit(
            "Backup/restore did not complete. The original database is not overwritten; inspect destination state before retry."
        ) from None
