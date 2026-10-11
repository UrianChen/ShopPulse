"""Record installed runtime distributions, versions and bundled license notices."""

import json
import re
from importlib import metadata
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text())
    packages = {p["name"]: p for p in lock["package"]}
    pending = [re.split(r"[\[<>=; ]", d)[0] for d in project["project"]["dependencies"]]
    names = set()
    while pending:
        name = pending.pop()
        if name in names:
            continue
        names.add(name)
        package = packages[name]
        pending += [d["name"] for d in package.get("dependencies", [])]
        for dependencies in package.get("optional-dependencies", {}).values():
            pending += [d["name"] for d in dependencies]
    records = []
    notice_root = ROOT / "licenses"
    for name in sorted(names):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            records.append(
                {
                    "ecosystem": "python",
                    "name": name,
                    "version": packages[name]["version"],
                    "license": "See upstream; platform-specific package not installed",
                }
            )
            continue
        meta = dist.metadata
        license_name = (
            meta.get("License-Expression")
            or meta.get("License")
            or "; ".join(
                c.split(" :: ")[-1]
                for c in meta.get_all("Classifier", [])
                if c.startswith("License ::")
            )
            or "See bundled notices/upstream"
        )
        notices = []
        for index, file in enumerate(dist.files or []):
            if ".dist-info/" not in str(file) or not re.search(
                r"license|copying|notice", file.name, re.IGNORECASE
            ):
                continue
            destination = notice_root / "python" / name / f"{index}-{file.name}.txt"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(Path(dist.locate_file(file)).read_bytes())
            notices.append(destination.relative_to(ROOT).as_posix())
        records.append(
            {
                "ecosystem": "python",
                "name": name,
                "version": dist.version,
                "license": license_name[:300],
                "notices": notices,
            }
        )
    npm = json.loads((ROOT / "frontend/package-lock.json").read_text())
    for location, package in sorted(npm["packages"].items()):
        if not location or package.get("dev"):
            continue
        notices = []
        folder = ROOT / "frontend" / location
        if folder.is_dir():
            for file in sorted(folder.iterdir()):
                if file.is_file() and re.match(
                    r"license|copying|notice", file.name, re.IGNORECASE
                ):
                    destination = (
                        notice_root
                        / "npm"
                        / location.replace("node_modules/", "")
                        / f"{file.name}.txt"
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(file.read_bytes())
                    notices.append(destination.relative_to(ROOT).as_posix())
        records.append(
            {
                "ecosystem": "npm",
                "name": location.split("node_modules/")[-1],
                "version": package["version"],
                "license": package.get("license", "See upstream"),
                "notices": notices,
            }
        )
    (notice_root / "dependency-inventory.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Recorded {len(records)} runtime dependency entries; font notice separately bundled"
    )


if __name__ == "__main__":
    main()
