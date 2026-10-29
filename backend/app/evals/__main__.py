"""Evaluation CLI.

python -m app.evals run                      # offline suite, scripted reference policy
python -m app.evals run --gate               # fail when gated metrics regress vs baseline
python -m app.evals run --suite live --model-config <id> [--judge-config <id>]
python -m app.evals export-labels --run <run.json> --out labels.csv
python -m app.evals calibrate --labels labels.csv
"""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.evals import harness, judge
from app.evals.policies import transport_for

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "cases.json"
BASELINE = ROOT / "evals" / "baseline.json"
OUTPUT = ROOT.parent / ".cache" / "evals"


def model_config(config_id):
    from sqlalchemy.orm import Session

    from app.db.models import ModelConfig
    from app.db.session import engine
    from app.providers.credentials import decrypt

    with Session(engine()) as db:
        item = db.get(ModelConfig, uuid.UUID(config_id))
        if item is None or not (item.capabilities or {}).get("usable"):
            raise SystemExit("Model config not found or not tested as usable.")
        config = {
            field: getattr(item, field)
            for field in (
                "base_url",
                "model_name",
                "protocol",
                "timeout_seconds",
                "token_limit_parameter",
                "product_name_mode",
                "capabilities",
            )
        }
        return config, decrypt(item)


def run(args):
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only.split(","))]
    cases = cases[: args.max_cases] if args.max_cases else cases
    if args.suite == "live":
        if not args.model_config:
            raise SystemExit("--model-config is required for the live suite.")
        from app.providers.egress import post

        config, key = model_config(args.model_config)
        transport, label = post, config["model_name"]
    else:
        config = {
            "base_url": "https://eval.invalid/v1",
            "model_name": args.policy,
            "protocol": args.protocol,
            "timeout_seconds": 30,
            "token_limit_parameter": "none",
            "product_name_mode": "sku_only",
            "capabilities": {
                "usable": True,
                "strategy": "native_tools",
                "native_json": True,
                "json_schema": True,
            },
        }
        key, transport, label = "", transport_for(args.policy), args.policy
    judge_config = judge_key = None
    if args.judge_config:
        judge_config, judge_key = model_config(args.judge_config)
    results = []
    for case in cases:
        result = harness.run_case(case, transport, config, key)
        if judge_config:
            result["judge"] = judge.llm_judge(result, case, judge_config, judge_key)
        else:
            result["judge"] = judge.heuristic_judge(result)
        results.append(result)
        print(
            f"{case['id']:<24} success={result['success']:.0f} repairs={result['repairs']} "
            f"entities={result['entity_coverage']:.2f} rules={result['rule_mention']:.2f} "
            f"tools={result['tool_calls']} error={result['error_code']}"
        )
    summary = harness.aggregate(results)
    report = {
        "suite": args.suite,
        "policy": label,
        "protocol": config.get("protocol"),
        "created_at": datetime.now(UTC).isoformat(),
        **harness.versions(),
        "aggregate": summary,
        "cases": results,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    out = (
        Path(args.out)
        if args.out
        else OUTPUT / f"{args.suite}-{label}-{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    )
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved {out}")
    if args.update_baseline:
        baseline = {
            **harness.versions(),
            "suite": args.suite,
            "policy": label,
            "aggregate": summary,
        }
        Path(args.baseline).write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Baseline updated: {args.baseline}")
    if args.gate:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))["aggregate"]
        failures = harness.gate(summary, baseline, args.tolerance)
        if failures:
            print("REGRESSION:\n" + "\n".join(failures))
            return 1
        print("PASS: no gated metric regressed")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.evals")
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--suite", choices=["offline", "live"], default="offline")
    runner.add_argument("--policy", default="reference")
    runner.add_argument(
        "--protocol",
        choices=["openai_chat", "openai_responses", "anthropic_messages"],
        default="openai_chat",
    )
    runner.add_argument("--model-config")
    runner.add_argument("--judge-config")
    runner.add_argument("--cases", default=str(CASES))
    runner.add_argument("--only")
    runner.add_argument("--max-cases", type=int)
    runner.add_argument("--out")
    runner.add_argument("--baseline", default=str(BASELINE))
    runner.add_argument("--gate", action="store_true")
    runner.add_argument("--tolerance", type=float, default=0.05)
    runner.add_argument("--update-baseline", action="store_true")
    labels = commands.add_parser("export-labels")
    labels.add_argument("--run", required=True)
    labels.add_argument("--out", required=True)
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--labels", required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        return run(args)
    if args.command == "export-labels":
        judge.export_labels(json.loads(Path(args.run).read_text(encoding="utf-8")), args.out)
        print(f"Saved {args.out}")
        return 0
    print(json.dumps(judge.calibrate(args.labels), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
