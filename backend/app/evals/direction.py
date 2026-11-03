"""Measure the DIRECTION_MISMATCH lint against hand-labelled sentences.

The lint is a soft review item today. These counts are the evidence for (or against) turning it
into a hard validation check: a false positive there would reject a correct report.
"""

import json
from pathlib import Path

from app.reports.evidence import direction_mismatch

SENTENCES = Path(__file__).resolve().parents[2] / "evals" / "direction.json"


def measure(path=SENTENCES):
    items = json.loads(Path(path).read_text(encoding="utf-8"))["sentences"]
    false_positives, false_negatives = [], []
    for item in items:
        signs = item["sign"] if isinstance(item["sign"], list) else [item["sign"]]
        flagged = direction_mismatch(item["text"], [s == "+" for s in signs])
        if flagged and not item["mismatch"]:
            false_positives.append(item["id"])
        elif item["mismatch"] and not flagged:
            false_negatives.append(item["id"])
    mismatches = sum(1 for item in items if item["mismatch"])
    caught = mismatches - len(false_negatives)
    flagged = caught + len(false_positives)
    return {
        "sentences": len(items),
        "mismatches": mismatches,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": round(caught / flagged, 4) if flagged else None,
        "recall": round(caught / mismatches, 4) if mismatches else None,
    }
