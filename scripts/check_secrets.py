"""Local credential regression. Values stay in memory; model keys stay inside the API container."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compose",
        action="store_true",
        help="Also scan backend storage and decrypted model keys inside the running API",
    )
    args = parser.parse_args()
    files = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    paths = {ROOT / name for name in files if name}
    for directory in (
        "frontend/dist",
        "frontend/test-results",
        "logs",
    ):
        paths.update(p for p in (ROOT / directory).rglob("*") if p.is_file())
    needles = [
        p.read_bytes().strip() for p in (ROOT / "secrets").glob("*") if p.is_file()
    ]
    needles = [n for n in needles if len(n) >= 12]
    combined = bytearray()
    for path in paths:
        data = path.read_bytes()
        if any(value in data for value in needles):
            raise SystemExit("FAIL: a local secret value was found; inspect privately")
        if args.compose:
            combined.extend(data)
            combined.extend(b"\n")
    print(
        f"PASS: {len(paths)} candidate source/build/test/log files contain no local secret values"
    )
    if args.compose:
        logs = subprocess.run(
            ["docker", "compose", "logs", "--no-color", "api", "worker"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        combined.extend(logs.stdout + logs.stderr)
        if any(value in combined for value in needles):
            raise SystemExit(
                "FAIL: a local secret value was found in supplied artifacts/logs"
            )
        checked = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "api",
                "python",
                "-m",
                "app.ops.archive",
                "scan-secrets",
            ],
            cwd=ROOT,
            input=bytes(combined),
            capture_output=True,
            check=False,
        )
        if checked.returncode:
            raise SystemExit("Backend secret scan failed; inspect privately")
        print(checked.stdout.decode().strip())


if __name__ == "__main__":
    main()
