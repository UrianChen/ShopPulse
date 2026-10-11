import json
import os
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
    ToolResult,
    now,
)
from app.jobs.queue import owned
from app.providers.credentials import decrypt
from app.reports.evidence import render
from app.reports.schema import BUDGETS, PROMPT_VERSION, RULE_VERSION
from app.reports.tools import LABELS, LIMITATIONS, ToolRegistry, metric_facts, topic_facts

FINAL = {"ready", "ready_with_warnings", "failed"}


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
        "stats": {
            "active_skus": count(MetricProduct.paid_units > 0, MetricProduct.sku.is_not(None)),
            "negative_sales": count(MetricProduct.net_sales < 0),
            "unmapped": count(MetricProduct.sku.is_(None)),
        },
    }


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
    facts = metric_facts(registry.evidence)
    summary = [
        render(f, registry.evidence, result["currency"], result["currency_exponent"])
        for f in facts[:4]
    ]
    return {
        "schema_version": "1.0",
        "report_id": str(report.id),
        "revision": report.revision,
        "title": report.title,
        "generation_mode": "deterministic",
        "template_version": "1.0",
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
        "findings": [],
        "recommendations": [
            {
                "action": "先核对成本、退款及数据覆盖，再复盘主要商品的变化。",
                "priority": "medium",
                "effort": "small",
                "verification_metric": "net_sales",
                "suggested_review_window": "next_week",
                "evidence_refs": [core["get_data_quality"]["evidence_id"]],
            }
        ],
        "limitations": LIMITATIONS,
        "warnings": result["warnings"],
        "evidence_index": [
            {key: ev[key] for key in ("evidence_id", "tool", "result_hash", "run_id")}
            for ev in registry.evidence
        ],
    }


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
    return {"config": report.model_snapshot, "key": key}, None


def model_process(request, timeout, cancelled=None):
    env = os.environ.copy()
    env["MODEL_ALLOWED_ORIGINS"] = json.dumps(settings().model_allowed_origins)
    process = subprocess.Popen(
        [sys.executable, "-m", "app.reports.runner"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    done, aborted = threading.Event(), threading.Event()

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

    watcher = threading.Thread(target=watch, daemon=True) if cancelled else None
    if watcher:
        watcher.start()
    try:
        # One communicate call must own the full pipe write. Short timeout retries with None
        # can abandon a partially written stdin on POSIX, leaving the child waiting for EOF.
        output, _ = process.communicate(
            json.dumps(request, ensure_ascii=False).encode(), timeout=max(1, timeout)
        )
        if aborted.is_set():
            raise subprocess.TimeoutExpired("cancelled", timeout)
        if process.returncode != 0:
            raise ValueError("RUNNER_FAILED")
        return json.loads(output)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return {
            "analysis": None,
            "error_code": "TIMEOUT",
            "usage": {},
            "steps": [],
            "extra_evidence": [],
        }
    except Exception:
        process.kill()
        process.communicate()
        raise
    finally:
        done.set()
        if watcher:
            watcher.join(timeout=2)


def question_intent(question, query):
    if re.search(
        r"去年|明年|下周|下个月|上个月|last year|next week|another.*(?:period|dataset)|"
        r"其他.*(?:日期|店铺|数据)|换.*(?:范围|版本)|全店",
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
        registry = ToolRegistry(context, str(report.id), str(run.id))
        if message_row or report.content:
            evidence_ids = [uuid.UUID(e["evidence_id"]) for e in report.content["evidence_index"]]
            registry.evidence = [
                ev.payload
                for ev in db.scalars(
                    select(ToolResult).where(
                        ToolResult.report_id == report.id, ToolResult.id.in_(evidence_ids)
                    )
                )
            ]
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
        credential, reason = model_request(db, report)
        if reserved:
            credential, reason = None, "MODEL_RETRY_SUPPRESSED"
        if intent in {"out_of_scope", "missing_data"}:
            credential, reason = None, intent.upper()
        run.status = "analyzing" if credential else "computing"
        run.usage = {"tools": registry.calls, "requests_reserved": 4 if credential else 0}
        run.steps = [
            {
                "phase": "computing",
                "tools": registry.calls,
                "evidence_count": len(registry.evidence),
            },
            {"phase": run.status},
        ]
        request = {
            "report_id": str(report.id),
            "run_id": str(run.id),
            "context": context,
            "evidence": registry.evidence,
            "kind": "question" if message_row else "report",
            "intent": intent,
        }
        run_id = run.id
    output = {
        "analysis": None,
        "error_code": reason,
        "usage": {"tools": registry.calls, "requests": 0},
        "steps": [],
        "extra_evidence": [],
    }
    if credential:

        def cancelled():
            with Session(db_module.engine()) as db:
                return not db.scalar(select(Job.id).where(*owned(job)))

        try:
            output = model_process(
                {**request, **credential}, 175 - (time.monotonic() - started), cancelled
            )
        except Exception:
            output["error_code"] = "MODEL_EXECUTION_FAILED"
        finally:
            credential = None
    commit(job, run_id, output, intent)


def commit(job, run_id, output, intent):
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
        if job.type == "report_question":
            msg = db.get(ReportMessage, uuid.UUID(job.payload["message_id"]))
            evidence = list(db.scalars(select(ToolResult).where(ToolResult.report_id == report.id)))
            fallback_summary = [
                render(
                    fact,
                    [ev.payload for ev in evidence],
                    report.content["metrics"]["currency"],
                    report.content["metrics"]["currency_exponent"],
                )
                for fact in topic_facts([ev.payload for ev in evidence], intent)
            ]
            text = (
                "此问题需要其他范围的数据，请通过新建报告选择日期、版本或 SKU；原报告保持不变。"
                if intent == "out_of_scope"
                else (
                    "当前未提供广告、流量或库存数据，无法判断投放效果、转化或补货数量。"
                    "请补充对应数据后验证。"
                )
                if intent == "missing_data"
                else "以下为原报告的可核验摘要；请结合退款原因、成本记录和商品明细继续核查。"
            )
            msg.answer = {
                "generation_mode": mode,
                "message": text,
                "analysis": output["analysis"],
                "summary": fallback_summary
                if not output["analysis"]
                else output["analysis"]["summary"],
                "limitations": LIMITATIONS,
                "error_code": error,
                "new_analysis_required": intent == "out_of_scope",
                "run_id": str(run_id),
                "evidence_index": report.content["evidence_index"]
                + [
                    {k: e[k] for k in ("evidence_id", "tool", "result_hash", "run_id")}
                    for e in output["extra_evidence"]
                ],
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
            content["evidence_index"] += [
                {k: e[k] for k in ("evidence_id", "tool", "result_hash", "run_id")}
                for e in output["extra_evidence"]
            ]
            content["run_id"] = str(run_id)
            report.content = content
            report.status = (
                "ready_with_warnings"
                if (error and error != "NO_MODEL") or content["warnings"]
                else "ready"
            )
        run.status, run.completed_at, run.error_code = "completed", now(), error
        run.usage = {**run.usage, **output["usage"]}
        run.steps = (
            run.steps
            + output["steps"]
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
