"""Build a reproducible source archive from an allowlist; exclude local secrets."""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {
    "VERSION",
    "README.md",
    "LICENSE",
    ".gitignore",
    ".dockerignore",
    ".env.example",
    "compose.yaml",
    "compose.dev.yaml",
    "compose.mock.yaml",
}
TREES = {"backend", "frontend", "deploy", "docs", "licenses", "samples", "scripts", ".github"}
EXCLUDED = {
    ".git",
    ".cache",
    ".venv",
    ".uv-cache",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "data",
    "logs",
    "secrets",
    "backups",
    "output",
    "test-results",
    "playwright-report",
    "coverage",
    "htmlcov",
}
EXTENSIONS = {
    ".py",
    ".tsx",
    ".ts",
    ".css",
    ".html",
    ".json",
    ".toml",
    ".lock",
    ".ini",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".csv",
    ".xlsx",
    ".ttf",
    ".png",
    ".svg",
    ".pdf",
    ".zip",
    ".conf",
    ".mako",
}


def source_files(root):
    def walk(directory):
        for path in sorted(directory.iterdir()):
            if path.name in EXCLUDED or path.name.endswith(".egg-info"):
                continue
            if path.is_symlink() or (
                hasattr(path, "is_junction") and path.is_junction()
            ):
                raise ValueError("Source tree contains a symlink/junction")
            if path.is_dir():
                yield from walk(path)
            elif (
                path.suffix in EXTENSIONS
                or path.name in {"Dockerfile", ".gitignore", ".python-version"}
            ) and path.name not in {"coverage.json", "credentials.json"}:
                yield path

    for name in sorted(TOP_FILES):
        path = root / name
        if path.is_symlink():
            raise ValueError("Source file is a symlink")
        if path.is_file():
            yield path
    for name in sorted(TREES):
        directory = root / name
        if directory.is_symlink() or (
            hasattr(directory, "is_junction") and directory.is_junction()
        ):
            raise ValueError("Source directory is a symlink/junction")
        if directory.is_dir():
            yield from walk(directory)


def build(root, destination):
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.\d+)?", version):
        raise ValueError("Invalid VERSION")
    prefix = f"ShopPulse-{version}"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{prefix}-source.zip"
    needles = [
        p.read_bytes().strip() for p in (root / "secrets").glob("*") if p.is_file()
    ]
    needles = [n for n in needles if len(n) >= 12]
    contents = {}
    for path in source_files(root):
        data = path.read_bytes()
        if any(n in data for n in needles):
            raise ValueError("Local secret detected; release refused")
        contents[path.relative_to(root).as_posix()] = data
    manifest = {
        "version": version,
        "kind": "source-release",
        "license_confirmed": "LICENSE" in contents,
        "files": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(contents.items())
        },
    }
    contents["MANIFEST.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode()
    # Fixed metadata/order make identical inputs produce identical ZIP bytes.
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as output:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo(f"{prefix}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(entry, data)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )
    print(f"Built {archive.name}: {len(manifest['files'])} files; SHA-256 {digest}")
    if not manifest["license_confirmed"]:
        print("WARNING: source archive has no project LICENSE")
    return archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "output/releases")
    args = parser.parse_args()
    build(ROOT, args.output)


if __name__ == "__main__":
    main()
