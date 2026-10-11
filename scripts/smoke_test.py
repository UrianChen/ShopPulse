"""Check a running API, database and worker without creating demonstration jobs."""

import argparse
import json
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()
    base = args.url.rstrip("/") + "/api/v1"

    def get(path):
        with urlopen(base + path, timeout=15) as response:
            return json.load(response)["data"]

    assert get("/health/ready")["status"] == "ready"
    assert get("/workspace")["name"]
    for _ in range(40):
        if any(worker["online"] for worker in get("/operations/status")["workers"]):
            print("PASS: API, database, workspace and worker heartbeat")
            return
        time.sleep(1)
    raise SystemExit("No online worker detected within 40 seconds")


if __name__ == "__main__":
    main()
