import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import session as db_module
from app.db.models import (
    AgentRun,
    DatasetVersion,
    Job,
    MetricProduct,
    MetricSnapshot,
    ModelConfig,
    Report,
    ReportMessage,
    ReportSchedule,
    ToolResult,
    now,
)
from app.jobs.queue import owned
from app.observability.tracing import span, trace_id, traceparent
from app.providers.credentials import decrypt
from app.reports.drill import drill_payload, scoped_query
from app.reports.evidence import render, validate_analysis, validate_answer
from app.reports.followups import (
    create_action_items,
    followups_for,
    notes_for,
    record_evaluations,
)
from app.reports.grammar import EvidenceError
from app.reports.schema import BUDGETS, GRAMMAR_VERSION, PROMPT_VERSION, RULE_VERSION
from app.reports.tools import (
    LABELS,
    ToolError,
    ToolRegistry,
    limitations,
    metric_facts,
    topic_facts,
)

FINAL = {"ready", "ready_with_warnings", "failed"}
CHILD_LIMIT = 16 * 1024 * 1024
FALLBACK = {
    "zh": {
        "out_of_scope": "此问题需要其他范围的数据，请通过新建报告选择日期、版本或 SKU；"
        "原报告保持不变。",
        "missing_data": "当前未提供广告、流量或库存数据，无法判断投放效果、转化或补货数量。"
        "请补充对应数据后验证。",
        "default": "以下为原报告的可核验摘要；请结合退款原因、成本记录和商品明细继续核查。",
        "recommendation": "先核对成本、退款及数据覆盖，再复盘主要商品的变化。",
    },
    "en": {
        "out_of_scope": "This question needs data from another scope. Create a new report with "
        "the dates, dataset or SKUs you need; the original report stays unchanged.",
        "missing_data": "Advertising, traffic and inventory data are not provided, so campaign "
        "effect, conversion and restocking cannot be assessed. Add that data to verify.",
        "default": "Below is the verifiable summary of the original report; check refund "
        "reasons, cost records and product details next.",
        "recommendation": "Check costs, refunds and data coverage first, then review the main "
        "product changes.",
    },
}


def context_for(db, report):
    snapshot = db.get(MetricSnapshot, report.metric_snapshot_id)
    rankings = {}
    for metric in ("net_sales", "gross_profit", "refund_amount", "paid_units"):
        for direction in ("asc", "desc"):
            column = getattr(MetricProduct, metric)
            order = column.asc() if direction == "asc" else column.desc()
            rows = db.scalars(
                select(MetricProduct)
                .where(MetricProduct.snapshot_id == snapshot.id)
                .order_by(order.nulls_last(), MetricProduct.group_key)
                .limit(50)
            )
            rankings[f"{metric}:{direction}"] = [p.payload for p in rows]
    # Filter before LIMIT: estimated losses must not hide confirmed loss-making SKUs.
    rankings["confirmed_negative_profit"] = [
        p.payload
        for p in db.scalars(
            select(MetricProduct)
            .where(
                MetricProduct.snapshot_id == snapshot.id,
                MetricProduct.gross_profit < 0,
                MetricProduct.payload["current"]["metrics"]["gross_profit"]["quality"].as_string()
                == "confirmed",
            )
            .order_by(MetricProduct.gross_profit, MetricProduct.group_key)
            .limit(50)
        )
    ]
    missing_cost = [
        p.payload
        for p in db.scalars(
            select(MetricProduct)
            .where(
                MetricProduct.snapshot_id == snapshot.id,
                MetricProduct.payload["current"]["quality"]["missing_cost_rows"].as_integer() > 0,
            )
            .order_by(MetricProduct.net_sales.desc().nulls_last(), MetricProduct.group_key)
            .limit(20)
        )
    ]

    def count(*conditions):
        return db.scalar(
            select(func.count())
            .select_from(MetricProduct)
            .where(MetricProduct.snapshot_id == snapshot.id, *conditions)
        )

    return {
        "result": snapshot.result,
        "rankings": rankings,
        "rules": report.rules,
        "language": report.language,
        "missing_cost": missing_cost,
        "followups": followups_for(db, report, snapshot.result),
        "notes": notes_for(db, report, snapshot.result),
        "stats": {
            "active_skus": count(MetricProduct.paid_units > 0, MetricProduct.sku.is_not(None)),
            "negative_sales": count(MetricProduct.net_sales < 0),
            "unmapped": count(MetricProduct.sku.is_(None)),
        },
    }


def report_evidence(db, report):
    return [
        r.payload
        for r in db.scalars(
            select(ToolResult)
            .where(ToolResult.report_id == report.id)
            .order_by(ToolResult.created_at, ToolResult.id)
        )
    ]


def make_drill(dataset_id, snapshot, query):
    """Recompute one SKU from frozen order lines in the worker process (never the model process)."""

    def drill(sku):
        from app.metrics.service import load_rows

        scoped = scoped_query(query, sku)
        with Session(db_module.engine()) as db:
            dataset = db.get(DatasetVersion, uuid.UUID(dataset_id))
            rows = load_rows(db, dataset, scoped, limit=settings().drill_row_limit)
        if len(rows) > settings().drill_row_limit:
            raise ToolError("ROWS_LIMIT")
        if not rows:
            raise ToolError("SKU_NOT_FOUND")
        return drill_payload(sku, rows, snapshot, query)

    return drill


def persist_evidence(db, evidence):
    for ev in evidence:
        if not db.get(ToolResult, uuid.UUID(ev["evidence_id"])):
            db.add(
                ToolResult(
                    id=uuid.UUID(ev["evidence_id"]),
                    report_id=uuid.UUID(ev["report_id"]),
                    run_id=uuid.UUID(ev["run_id"]),
                    tool=ev["tool"],
                    args_hash=ev["args_hash"],
                    payload=ev,
                )
            )


def deterministic(report, dataset, context, registry):
    core = registry.core()
    result = context["result"]
    language = getattr(report, "language", None) or "zh"
    facts = metric_facts(registry.evidence, language)
    summary = [
        render(f, registry.evidence, result["currency"], result["currency_exponent"], language)
        for f in facts[:4]
    ]
    followups = core.get("check_recommendation")
    notes = core.get("get_merchant_notes")
    return {
        "schema_version": "2.0",
        "report_id": str(report.id),
        "revision": report.revision,
        "title": report.title,
        "language": language,
        "generation_mode": "deterministic",
        "template_version": "2.0",
        "snapshot": {
            "dataset_id": str(dataset.id),
            "dataset_fingerprint": dataset.fingerprint,
            "cost_version_id": str(dataset.cost_version_id) if dataset.cost_version_id else None,
            "source_config": dataset.snapshot,
            "model": report.model_snapshot,
            "metric_snapshot_id": str(report.metric_snapshot_id),
            "engine_version": result["engine_version"],
            "metric_definition_version": result["metric_definition_version"],
            "source_as_of": result["source_as_of"],
            "rule_version": RULE_VERSION,
            "rules": report.rules,
            "prompt_version": PROMPT_VERSION,
            "grammar_version": GRAMMAR_VERSION,
        },
        "metrics": result,
        "metric_cards": [
            {
                "key": key,
                "label": label,
                "metric": result["current"]["metrics"][key],
                "evidence_id": core["calculate_metrics"]["evidence_id"],
            }
            for key, label in LABELS.items()
        ],
        "charts": [
            {
                "id": "sales_trend",
                "kind": "trend",
                "evidence_id": core["get_sales_trend"]["evidence_id"],
            },
            {
                "id": "sales_contributions",
                "kind": "contributions",
                "evidence_id": core["decompose_sales_change"]["evidence_id"],
            },
        ],
        "summary": summary,
        "products": core["rank_products"]["payload"]["items"],
        "anomalies": core["detect_anomalies"]["payload"],
        "action_followups": [
            {**item, "evidence_id": followups["evidence_id"]}
            for item in followups["payload"]["items"]
        ]
        if followups
        else [],
        "merchant_notes": [
            {**item, "evidence_id": notes["evidence_id"]} for item in notes["payload"]["items"]
        ]
        if notes
        else [],
        "findings": [],
        "recommendations": [
            {
                "action": FALLBACK[language]["recommendation"],
                "priority": "medium",
                "effort": "small",
                "verification_metric": "net_sales",
                "suggested_review_window": "next_week",
                "evidence_refs": [core["get_data_quality"]["evidence_id"]],
            }
        ],
        "limitations": limitations(language),
        "warnings": result["warnings"],
        "evidence_index": [
            {key: ev[key] for key in ("evidence_id", "tool", "result_hash", "run_id")}
            for ev in registry.evidence
        ],
    }


def consent_fields(report):
    return set(((report.model_snapshot or {}).get("consent") or {}).get("fields") or [])


def model_request(db, report):
    if not report.model_config_id:
        return None, "NO_MODEL"
    config = db.get(ModelConfig, report.model_config_id)
    if not config or config.revision != report.model_snapshot["revision"]:
        return None, "MODEL_CONFIG_CHANGED"
    if not (report.model_snapshot.get("capabilities") or {}).get("usable"):
        return None, "MODEL_UNAVAILABLE"
    if not config.capabilities or not config.capabilities.get("usable"):
        return None, "MODEL_UNAVAILABLE"
    if config.consent.get("revision") != config.revision:
        return None, "CONSENT_REQUIRED"
    try:
        key = decrypt(config)
    except Exception:
        return None, "CREDENTIAL_UNAVAILABLE"
    snapshot = dict(report.model_snapshot)
    snapshot.setdefault("protocol", "openai_chat")
    return {"config": snapshot, "key": key}, None


def _timeout_output(steps):
    return {
        "analysis": None,
        "raw_analysis": None,
        "error_code": "TIMEOUT",
        "usage": {},
        "steps": steps,
        "extra_evidence": [],
    }


def model_process(request, timeout, cancelled=None, tools=None, on_event=None):
    """Run the model subprocess and serve its tool requests over newline-delimited JSON."""
    env = os.environ.copy()
    env["MODEL_ALLOWED_ORIGINS"] = json.dumps(settings().model_allowed_origins)
    process = subprocess.Popen(
        [sys.executable, "-m", "app.reports.runner"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    lines, done, aborted = queue.Queue(), threading.Event(), threading.Event()
    deadline = time.monotonic() + max(1, timeout)
    steps = []

    def read():
        try:
            while True:
                line = process.stdout.readline(CHILD_LIMIT + 1)
                if not line or len(line) > CHILD_LIMIT:
                    break
                lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            lines.put(None)

    def watch():
        while not done.wait(1):
            try:
                stop = cancelled()
            except Exception:
                stop = True
            if stop:
                aborted.set()
                process.kill()
                return

    def write(data):
        # A writer thread bounds a blocked pipe write by the run deadline.
        failure = []

        def target():
            try:
                process.stdin.write(data)
                process.stdin.flush()
            except (OSError, ValueError) as error:
                failure.append(error)

        writer = threading.Thread(target=target, daemon=True)
        writer.start()
        writer.join(max(0.1, deadline - time.monotonic()))
        if writer.is_alive() or (failure and aborted.is_set()):
            raise subprocess.TimeoutExpired("runner", timeout)
        if failure:
            raise ValueError("RUNNER_PIPE")

    def reply(message):
        name, args = message.get("name"), message.get("args") or {}
        try:
            if tools is None:
                raise ToolError("TOOL_UNAVAILABLE")
            evidence = tools(name, args)
            body = {
                "type": "tool_result",
                "id": message.get("id"),
                "ok": True,
                "evidence": evidence,
            }
        except ToolError as error:
            body = {"type": "tool_result", "id": message.get("id"), "ok": False, "code": error.code}
        except Exception:
            body = {
                "type": "tool_result",
                "id": message.get("id"),
                "ok": False,
                "code": "TOOL_FAILED",
            }
        write((json.dumps(body, ensure_ascii=False) + "\n").encode("utf-8"))

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    watcher = threading.Thread(target=watch, daemon=True) if cancelled else None
    if watcher:
        watcher.start()
    try:
        write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("runner", timeout)
            try:
                line = lines.get(timeout=min(remaining, 1))
            except queue.Empty:
                if aborted.is_set():
                    raise subprocess.TimeoutExpired("cancelled", timeout) from None
                continue
            if line is None:
                if aborted.is_set():
                    raise subprocess.TimeoutExpired("cancelled", timeout)
                raise ValueError("RUNNER_FAILED")
            message = json.loads(line)
            kind = message.get("type")
            if kind == "event" and isinstance(message.get("step"), dict):
                steps.append(message["step"])
                if on_event:
                    try:
                        on_event(message["step"])
                    except Exception:
                        pass
            elif kind == "tool":
                reply(message)
            elif kind == "final":
                output = message.get("output") or {}
                output["steps"] = steps
                output.setdefault("extra_evidence", [])
                output.setdefault("analysis", None)
                return output
    except subprocess.TimeoutExpired:
        return _timeout_output(steps)
    finally:
        done.set()
        try:
            process.stdin.close()
        except (OSError, ValueError):
            pass
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        reader.join(timeout=2)
        if watcher:
            watcher.join(timeout=2)


def question_intent(question, query):
    if re.search(
        r"去年|明年|下周|下个月|上个月|last year|next week|next month|last month|"
        r"another.*(?:period|dataset)|其他.*(?:日期|店铺|数据)|换.*(?:范围|版本)|全店",
        question,
        re.I,
    ):
        return "out_of_scope"
    dates = re.findall(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", question)
    if dates:
        return "out_of_scope"  # Date-specific analysis requires an explicit new frozen query.
    if re.search(r"广告|流量|库存|补货|投放|转化|ROAS|ROI|inventory|advert", question, re.I):
        return "missing_data"
    if re.search(r"退款|refund", question, re.I):
        return "refund_review"
    if re.search(r"成本|毛利|利润|profit|cost", question, re.I):
        return "profit_review"
    if re.search(r"商品|产品|SKU|product", question, re.I):
        return "product_review"
    return "business_review"


def conversation_for(db, report, message_row, include_questions):
    rows = db.scalars(
        select(ReportMessage)
        .where(
            ReportMessage.report_id == report.id,
            ReportMessage.sequence < message_row.sequence,
            ReportMessage.status.in_(["ready", "ready_with_warnings"]),
        )
        .order_by(ReportMessage.sequence.desc())
        .limit(3)
    )
    history = []
    for row in reversed(list(rows)):
        answer = row.answer or {}
        entry = {"answer": [s["text"] for s in answer.get("summary") or []][:4]}
        if include_questions:
            entry["question"] = row.question
        history.append(entry)
    return history


def append_step(run_id, step):
    with Session(db_module.engine()) as db, db.begin():
        run = db.get(AgentRun, run_id, with_for_update=True)
        if run is not None and run.status in {"computing", "analyzing"}:
            run.steps = [*run.steps, {k: v for k, v in step.items() if k != "debug"}]


def execute(job):
    started = time.monotonic()
    with Session(db_module.engine()) as db, db.begin():
        current = db.scalar(select(Job).where(*owned(job)).with_for_update())
        if not current:
            return
        report = db.get(Report, uuid.UUID(job.payload["report_id"]), with_for_update=True)
        message_row = (
            db.get(ReportMessage, uuid.UUID(job.payload["message_id"]))
            if job.type == "report_question"
            else None
        )
        snapshot = db.get(MetricSnapshot, report.metric_snapshot_id)
        if snapshot.result is None:
            dependency = db.get(Job, snapshot.job_id)
            if dependency.status in {"queued", "running"}:
                current.status, current.lease_expires_at = "queued", None
                current.available_at = now() + timedelta(seconds=2)
                current.attempt -= 1
                report.status = "computing"
                return
            report.status, current.status, current.error_code = "failed", "failed", "METRICS_FAILED"
            current.lease_expires_at = None
            return
        # Reserve a whole model budget before starting external IO. After a crash we cannot
        # know how much the provider charged, so recovery does not repeat reserved calls.
        reserved = any(
            r.usage.get("requests_reserved", 0)
            for r in db.scalars(select(AgentRun).where(AgentRun.job_id == job.id))
        )
        # Previous interrupted attempts keep their trace but cannot publish a result.
        for old in db.scalars(
            select(AgentRun).where(
                AgentRun.job_id == job.id, AgentRun.status.in_(["computing", "analyzing"])
            )
        ):
            old.status, old.error_code, old.completed_at = "interrupted", "LEASE_LOST", now()
        run = AgentRun(
            prompt_version=PROMPT_VERSION,
            id=uuid.uuid4(),
            report_id=report.id,
            job_id=job.id,
            attempt=job.attempt,
            budgets=BUDGETS,
            steps=[{"phase": "computing"}],
            usage={},
        )
        db.add(run)
        db.flush()
        context = context_for(db, report)
        existing = report_evidence(db, report)
        registry = ToolRegistry(
            context,
            str(report.id),
            str(run.id),
            cache={(e["tool"], e["args_hash"]): e for e in existing},
        )
        if message_row or report.content:
            registry.evidence = existing
            intent = (
                question_intent(message_row.question, report.query)
                if message_row
                else "business_review"
            )
            if message_row:
                message_row.status = "running"
        else:
            report.content = deterministic(
                report, db.get(DatasetVersion, report.dataset_id), context, registry
            )
            persist_evidence(db, registry.evidence)
            report.status = "analyzing"
            intent = "business_review"
        core_count = len(registry.evidence)
        credential, reason = model_request(db, report)
        fields = consent_fields(report)
        if reserved:
            credential, reason = None, "MODEL_RETRY_SUPPRESSED"
        if intent == "missing_data" or (intent == "out_of_scope" and "question_text" not in fields):
            credential, reason = None, intent.upper()
        run.status = "analyzing" if credential else "computing"
        run.usage = {
            "tools": 0,
            "core_tools": core_count,
            "requests_reserved": BUDGETS["requests"] if credential else 0,
        }
        base_steps = [
            {"phase": "computing", "tools": core_count, "evidence_count": len(registry.evidence)},
            {"phase": run.status, "intent": intent},
        ]
        run.steps = base_steps
        result = context["result"]
        dataset = db.get(DatasetVersion, report.dataset_id)
        request = {
            "report_id": str(report.id),
            "run_id": str(run.id),
            "evidence": registry.evidence,
            "kind": "question" if message_row else "report",
            "intent": intent,
            "language": report.language or "zh",
            "dataset_id": result["dataset_id"],
            "currency": result["currency"],
            "currency_exponent": result["currency_exponent"],
            "scope": result["query"],
            "prompt_version": PROMPT_VERSION,
            "debug_capture": settings().agent_debug_capture,
        }
        if message_row:
            request["question"] = message_row.question if "question_text" in fields else None
            request["conversation"] = conversation_for(
                db, report, message_row, "question_text" in fields
            )
        drill = make_drill(str(dataset.id), dataset.snapshot, result["query"])
        run_id = run.id
        include_names = (report.model_snapshot or {}).get("product_name_mode") == "include_names"
    output = {
        "analysis": None,
        "error_code": reason,
        "usage": {"tools": 0, "requests": 0},
        "steps": [],
        "extra_evidence": [],
    }
    trace = None
    if credential:
        registry.drill = drill

        def cancelled():
            with Session(db_module.engine()) as db:
                return not db.scalar(select(Job.id).where(*owned(job)))

        with span(
            "agent.run",
            {
                "shoppulse.report_id": request["report_id"],
                "shoppulse.run_id": request["run_id"],
                "shoppulse.kind": request["kind"],
                "shoppulse.intent": intent,
                "shoppulse.prompt_version": PROMPT_VERSION,
                "gen_ai.request.model": (credential.get("config") or {}).get("model_name", ""),
            },
        ) as root:
            trace = trace_id(root)
            request["traceparent"] = traceparent()
            try:
                output = model_process(
                    {**request, **credential},
                    BUDGETS["seconds"] - 5 - (time.monotonic() - started),
                    cancelled,
                    tools=registry.execute,
                    on_event=lambda step: append_step(run_id, step),
                )
            except Exception:
                output["error_code"] = "MODEL_EXECUTION_FAILED"
            finally:
                credential = None
        # Defense in depth: re-validate the child's raw output against the parent's evidence.
        raw, output["analysis"] = output.get("raw_analysis"), None
        if raw is not None and not output.get("error_code"):
            validator = validate_answer if message_row else validate_analysis
            try:
                output["analysis"] = validator(
                    raw,
                    registry.evidence,
                    request["report_id"],
                    request["dataset_id"],
                    request["currency"],
                    request["currency_exponent"],
                    request["scope"],
                    request["language"],
                    include_names,
                )
            except (EvidenceError, ValueError, TypeError, KeyError):
                output["error_code"] = "PARENT_VALIDATION_FAILED"
        output["extra_evidence"] = registry.evidence[core_count:]
        output.setdefault("usage", {})["tools"] = registry.calls
    commit(job, run_id, output, intent, base_steps, trace)


def answer_for(report, intent, output, evidence):
    language = report.language or "zh"
    analysis = output["analysis"]
    if analysis:
        text = analysis["clarify"]["text"] if analysis["clarify"] else None
        return {
            "kind": analysis["kind"],
            "message": text,
            "analysis": {
                "findings": analysis["findings"],
                "recommendations": analysis["recommendations"],
            },
            "summary": analysis["answer"],
            "options": analysis["options"],
            "suggested_query": analysis["suggested_query"],
            "new_analysis_required": analysis["kind"] == "suggested_query",
        }
    result = report.content["metrics"]
    fallback = [
        render(fact, evidence, result["currency"], result["currency_exponent"], language)
        for fact in topic_facts(evidence, intent, language)
    ]
    return {
        "kind": "fallback",
        "message": FALLBACK[language].get(intent, FALLBACK[language]["default"]),
        "analysis": None,
        "summary": fallback,
        "options": [],
        "suggested_query": None,
        "new_analysis_required": intent == "out_of_scope",
    }


def commit(job, run_id, output, intent, base_steps=None, trace=None):
    with Session(db_module.engine()) as db, db.begin():
        current = db.scalar(select(Job).where(*owned(job)).with_for_update())
        if not current:
            return False
        report = db.get(Report, uuid.UUID(job.payload["report_id"]), with_for_update=True)
        run = db.get(AgentRun, run_id)
        error = output["error_code"]
        mode = (
            report.model_snapshot["capabilities"]["strategy"]
            if output["analysis"]
            else "deterministic"
        )
        persist_evidence(db, output["extra_evidence"])
        steps = output.get("steps") or []
        debug = [
            {"t_ms": s.get("t_ms"), "request": s.get("request"), **s["debug"]}
            for s in steps
            if isinstance(s.get("debug"), dict)
        ][:16]
        steps = [{k: v for k, v in s.items() if k != "debug"} for s in steps]
        new_index = [
            {k: e[k] for k in ("evidence_id", "tool", "result_hash", "run_id")}
            for e in output["extra_evidence"]
        ]
        if job.type == "report_question":
            msg = db.get(ReportMessage, uuid.UUID(job.payload["message_id"]))
            evidence = [
                ev.payload
                for ev in db.scalars(select(ToolResult).where(ToolResult.report_id == report.id))
            ]
            known = {e["evidence_id"] for e in evidence}
            evidence += [e for e in output["extra_evidence"] if e["evidence_id"] not in known]
            msg.answer = {
                "generation_mode": mode,
                **answer_for(report, intent, output, evidence),
                "limitations": limitations(report.language or "zh"),
                "error_code": error,
                "run_id": str(run_id),
                "evidence_index": report.content["evidence_index"] + new_index,
            }
            msg.status = (
                "ready"
                if output["analysis"] or error in {"NO_MODEL", "OUT_OF_SCOPE", "MISSING_DATA"}
                else "ready_with_warnings"
            )
        else:
            content = dict(report.content)
            content["generation_mode"] = mode
            content["model_error_code"] = error
            if output["analysis"]:
                content.update(output["analysis"])
            content["evidence_index"] = content["evidence_index"] + new_index
            content["run_id"] = str(run_id)
            report.content = content
            report.status = (
                "ready_with_warnings"
                if (error and error != "NO_MODEL") or content["warnings"]
                else "ready"
            )
            create_action_items(db, report, content["recommendations"])
            record_evaluations(db, content.get("action_followups") or [], report.id)
            notify(db, report)
        run.status, run.completed_at, run.error_code = "completed", now(), error
        run.usage = {**run.usage, **output.get("usage", {})}
        run.trace_id = trace
        run.debug = debug or None
        run.steps = (
            (base_steps or run.steps[:2])
            + steps
            + [
                {"phase": "validating", "repaired": output.get("repaired", False)},
                {"phase": "completed", "generation_mode": mode},
            ]
        )
        current.status, current.error_code, current.lease_expires_at = "succeeded", None, None
        current.result = {
            "report_id": str(report.id),
            "run_id": str(run_id),
            "generation_mode": mode,
        }
        current.updated_at = now()
        return True


def notify(db, report):
    if not report.schedule_id:
        return
    schedule = db.get(ReportSchedule, report.schedule_id)
    if schedule is None or not schedule.webhook_ciphertext:
        return
    from app.ingestion.service import schedule as enqueue

    enqueue(
        db,
        report.workspace_id,
        "notify_webhook",
        {"report_id": str(report.id), "schedule_id": str(schedule.id)},
    )


def fail(db, job, code):
    report = db.get(Report, uuid.UUID(job.payload["report_id"]))
    if job.type == "report_question":
        msg = db.get(ReportMessage, uuid.UUID(job.payload["message_id"]))
        if msg:
            msg.status = "failed"
    elif report:
        report.status = "ready_with_warnings" if report.content else "failed"
        if report.content:
            report.content = {
                **report.content,
                "generation_mode": "deterministic",
                "model_error_code": code,
            }
    for run in db.scalars(
        select(AgentRun).where(
            AgentRun.job_id == job.id, AgentRun.status.in_(["computing", "analyzing"])
        )
    ):
        run.status, run.error_code, run.completed_at = "failed", code, now()


def fail_job(job):
    with Session(db_module.engine()) as db, db.begin():
        current = db.scalar(select(Job).where(*owned(job)).with_for_update())
        if not current:
            return
        fail(db, current, "EXECUTION_FAILED")
        current.status, current.error_code, current.lease_expires_at = (
            "failed",
            "EXECUTION_FAILED",
            None,
        )
