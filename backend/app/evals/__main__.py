"""Evaluation CLI.

python -m app.evals run                      # offline suite, scripted reference policy
python -m app.evals run --gate               # fail when gated metrics regress vs baseline
python -m app.evals run --suite live --model-config <id> [--judge-config <id>] [--repeat 3]
                         [--max-requests N] [--max-tokens N]   # spend caps across the whole run
python -m app.evals compare <before.json> <after.json> [--out diff.md]
python -m app.evals export-labels --run <run.json> --out labels.csv   # LLM-judged runs only
python -m app.evals calibrate --labels labels.csv
python -m app.evals direction                # DIRECTION_MISMATCH lint vs labelled sentences
"""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.evals import compare, direction, harness, judge
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
                "review_model_name",
                "protocol",
                "timeout_seconds",
                "token_limit_parameter",
                "product_name_mode",
                "capabilities",
            )
        }
        return config, decrypt(item)


def spent(result):
    """Provider requests and tokens one case run used, its LLM judgement included."""
    usage = (result.get("judge") or {}).get("usage") or {}
    return {
        "requests": (result.get("requests") or 0) + usage.get("requests", 0),
        "tokens": (result.get("input_tokens") or 0)
        + (result.get("output_tokens") or 0)
        + usage.get("tokens", 0),
    }


def over_cap(total, largest, caps):
    """The cap the next case could break, judged by the costliest case so far, or None."""
    for key, cap in caps.items():
        if cap is not None and (total[key] >= cap or total[key] + largest[key] > cap):
            return f"max_{key}"
    return None


def run(args):
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only.split(","))]
    cases, skipped = harness.runnable(cases, args.suite)
    if skipped:
        print(
            f"Skipped {len(skipped)} live-only case(s) offline: "
            + ", ".join(c["id"] for c in skipped)
            + " (scored by --suite live)"
        )
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
    caps = {"requests": args.max_requests, "tokens": args.max_tokens}
    total, largest = {"requests": 0, "tokens": 0}, {"requests": 0, "tokens": 0}
    results, stopped = [], None
    for repeat in range(args.repeat):
        for case in cases:
            # Stop before a case that could break a cap; a case in flight always finishes.
            reason = over_cap(total, largest, caps)
            if reason:
                stopped = {
                    "reason": reason,
                    "cases_done": len(results),
                    "cap": caps[reason.removeprefix("max_")],
                    "spent": dict(total),
                }
                break
            result = harness.run_case(case, transport, config, key)
            result["repeat"] = repeat
            if judge_config:
                result["judge"] = judge.llm_judge(result, case, judge_config, judge_key)
            results.append(result)
            for name, value in spent(result).items():
                total[name] += value
                largest[name] = max(largest[name], value)
            causes = result.get("cause_recall")
            print(
                f"{case['id']:<24} #{repeat} success={result['success']:.0f} "
                f"repairs={result['repairs']} pipeline={result.get('pipeline_accuracy')} "
                f"causes={'-' if causes is None else f'{causes:.2f}'} "
                f"requests={result['requests']} error={result['error_code']}"
            )
        if stopped:
            break
    summary = harness.aggregate(results)
    # A repeat cut short by a cap would skew the spread; only complete repeats count.
    complete = len(results) // len(cases) if cases else 0
    report = {
        "suite": args.suite,
        "policy": label,
        "protocol": config.get("protocol"),
        "created_at": datetime.now(UTC).isoformat(),
        **harness.versions(),
        "repeat": args.repeat,
        "spend": {**total, "caps": caps},
        **({"stopped": stopped} if stopped else {}),
        "aggregate": summary,
        "spread": harness.spread([r for r in results if r["repeat"] < complete], complete),
        "cases": results,
    }
    out = (
        Path(args.out)
        if args.out
        else OUTPUT / f"{args.suite}-{label}-{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    )
    # Only the target's folder: the default cache folder may sit on a read-only filesystem.
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved {out}")
    if stopped:
        print(
            f"STOPPED: {stopped['reason']} {stopped['cap']} would be exceeded; "
            f"{stopped['cases_done']} of {len(cases) * args.repeat} case runs done "
            f"(spent {total['requests']} requests, {total['tokens']} tokens). "
            "The aggregate covers only those runs."
        )
        if args.update_baseline or args.gate:
            print("A stopped run is incomplete: no baseline update, gate fails.")
            return 1
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
    runner.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run every case N times; the report adds mean, stdev and range per metric",
    )
    runner.add_argument(
        "--max-requests",
        type=int,
        help="stop before the next case once provider requests (judge included) could exceed N",
    )
    runner.add_argument(
        "--max-tokens",
        type=int,
        help="stop before the next case once input + output tokens could exceed N",
    )
    differ = commands.add_parser("compare")
    differ.add_argument("before")
    differ.add_argument("after")
    differ.add_argument("--out")
    labels = commands.add_parser("export-labels")
    labels.add_argument("--run", required=True)
    labels.add_argument("--out", required=True)
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--labels", required=True)
    commands.add_parser("direction")
    args = parser.parse_args(argv)
    if args.command == "run":
        if args.repeat < 1:
            raise SystemExit("--repeat must be at least 1.")
        if any(cap is not None and cap < 1 for cap in (args.max_requests, args.max_tokens)):
            raise SystemExit("--max-requests and --max-tokens must be at least 1.")
        return run(args)
    if args.command == "direction":
        print(json.dumps(direction.measure(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "compare":
        before, after = (
            json.loads(Path(path).read_text(encoding="utf-8")) for path in (args.before, args.after)
        )
        text = compare.markdown(before, after)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"Saved {args.out}")
        else:
            print(text)
        return 0
    if args.command == "export-labels":
        judge.export_labels(json.loads(Path(args.run).read_text(encoding="utf-8")), args.out)
        print(f"Saved {args.out}")
        return 0
    print(json.dumps(judge.calibrate(args.labels), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
