"""Isolated untrusted file parsing. Parent enforces wall time; no DB or model access."""

import json
import os
import sys
from pathlib import Path

from app.ingestion.normalize import normalize
from app.ingestion.parser import ParseError, parse, preview


def main():
    if os.name != "nt":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        parsed = parse(Path(request["path"]), request["config"], request["max_rows"])
        if request["action"] == "parse":
            result = {"metadata": preview(parsed, request["kind"])}
        else:
            result = normalize(
                parsed,
                request["kind"],
                request["config"],
                request["resolutions"],
                request["sha256"],
                request["costs"],
            )
            result["summary"]["preview"] = preview(parsed, request["kind"])
    except ParseError as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "无法解析此文件，请检查文件类型、工作表、格式及资源限制。"}
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
