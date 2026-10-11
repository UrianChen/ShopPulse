"""Bounded metrics subprocess; consumes frozen JSON, never opens the database."""

import json
import os
import sys
from pathlib import Path


def main():
    if os.name != "nt":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    from app.metrics.engine import calculate

    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        result = calculate(request["rows"], request["snapshot"], request["query"])
    except Exception:
        result = {"error": "指标计算失败，请检查已发布版本和筛选范围。"}
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
