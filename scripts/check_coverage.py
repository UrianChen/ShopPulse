"""Require both line and branch coverage >=90% for authoritative business rules."""

import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
for target in ("app/metrics/engine.py", "app/ingestion/normalize.py"):
    entry = next(
        value
        for name, value in data["files"].items()
        if name.replace("\\", "/") == target
    )
    summary = entry["summary"]
    for covered, total, label in (
        ("covered_lines", "num_statements", "lines"),
        ("covered_branches", "num_branches", "branches"),
    ):
        percent = 100 * summary[covered] / max(1, summary[total])
        print(f"{target} {label}: {percent:.2f}%")
        if percent < 90:
            raise SystemExit("Critical business rule coverage is below 90%")
