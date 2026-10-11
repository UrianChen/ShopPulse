import json
import sys

from app.reports.workflow import ReportWorkflow


def main():
    try:
        request = json.loads(sys.stdin.buffer.read(16 * 1024 * 1024 + 1))
        output = ReportWorkflow(request).run()
    except Exception:
        output = {
            "analysis": None,
            "error_code": "MODEL_OUTPUT_INVALID",
            "usage": {},
            "steps": [],
            "extra_evidence": [],
        }
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
