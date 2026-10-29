"""Close the loop: recommendations become action items, later reports evaluate them."""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from sqlalchemy import select

from app.db.models import ActionItem, MerchantNote, Report, now

LOWER_IS_BETTER = {"refund_amount_rate"}
MAX_FOLLOWUPS = 10
MAX_NOTES = 20


def _period(query):
    return date.fromisoformat(query["start"]), date.fromisoformat(query["end_exclusive"])


def _ratio(value):
    with localcontext() as context:
        context.prec = 70
        return format(value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP), "f")


def evaluate(item, source, result):
    metric = item.verification_metric
    source_result = (source.content or {}).get("metrics") or {}
    baseline = ((source_result.get("current") or {}).get("metrics") or {}).get(metric)
    current = result["current"]["metrics"].get(metric)
    reason = None
    if sorted(source.query.get("skus") or []) != sorted(result["query"].get("skus") or []):
        reason = "SCOPE_CHANGED"
    elif source_result.get("currency") != result["currency"]:
        reason = "CURRENCY_CHANGED"
    elif not baseline or not current or baseline["value"] is None or current["value"] is None:
        reason = "VALUE_UNAVAILABLE"
    change_rate, state = None, "insufficient_data"
    if reason is None:
        with localcontext() as context:
            context.prec = 70
            before, after = Decimal(baseline["value"]), Decimal(current["value"])
            if before != 0:
                change_rate = _ratio((after - before) / abs(before))
            better = after < before if metric in LOWER_IS_BETTER else after > before
            state = "improved" if better else "not_improved"
    start, end = _period(source.query)
    return {
        "action_id": str(item.id),
        "action_text": item.text,
        "verification_metric": metric,
        "priority": item.priority,
        "status": item.status,
        "source_report_id": str(source.id),
        "source_period": [start.isoformat(), end.isoformat()],
        "state": state,
        "reason": reason,
        "baseline": baseline if reason is None else None,
        "current": current if reason is None else None,
        "change_rate": change_rate,
    }


def followups_for(db, report, result):
    """Earlier, non-dismissed action items whose review window has arrived."""
    start, end = _period(report.query)
    rows = db.execute(
        select(ActionItem, Report)
        .join(Report, Report.id == ActionItem.report_id)
        .where(
            ActionItem.workspace_id == report.workspace_id,
            ActionItem.status != "dismissed",
            ActionItem.report_id != report.id,
        )
        .order_by(ActionItem.created_at.desc(), ActionItem.position)
        .limit(50)
    )
    items = []
    for item, source in rows:
        if not source.content:
            continue
        _, source_end = _period(source.query)
        if source_end > start:
            continue
        if item.review_window == "next_month" and (end - source_end).days < 28:
            continue
        items.append(evaluate(item, source, result))
        if len(items) >= MAX_FOLLOWUPS:
            break
    return items


def notes_for(db, report, result):
    periods = [_period(result["query"])]
    if result["query"].get("compare_start"):
        periods.append(
            (
                date.fromisoformat(result["query"]["compare_start"]),
                date.fromisoformat(result["query"]["compare_end_exclusive"]),
            )
        )
    lo, hi = min(p[0] for p in periods), max(p[1] for p in periods)
    rows = db.scalars(
        select(MerchantNote)
        .where(
            MerchantNote.workspace_id == report.workspace_id,
            MerchantNote.start_date < hi,
            MerchantNote.end_exclusive > lo,
        )
        .order_by(MerchantNote.start_date, MerchantNote.id)
        .limit(MAX_NOTES)
    )
    return [
        {
            "id": str(n.id),
            "start": n.start_date.isoformat(),
            "end_exclusive": n.end_exclusive.isoformat(),
            "kind": n.kind,
            "text": n.text,
        }
        for n in rows
    ]


def create_action_items(db, report, recommendations):
    existing = set(db.scalars(select(ActionItem.position).where(ActionItem.report_id == report.id)))
    for position, item in enumerate(recommendations):
        if position in existing:
            continue
        db.add(
            ActionItem(
                id=uuid.uuid4(),
                workspace_id=report.workspace_id,
                report_id=report.id,
                position=position,
                text=item["action"][:500],
                verification_metric=item["verification_metric"],
                review_window=item["suggested_review_window"],
                priority=item["priority"],
                effort=item["effort"],
            )
        )


def record_evaluations(db, followups, report_id):
    for entry in followups:
        item = db.get(ActionItem, uuid.UUID(entry["action_id"]), with_for_update=True)
        if item is None:
            continue
        item.evaluation = {
            "state": entry["state"],
            "reason": entry["reason"],
            "change_rate": entry["change_rate"],
            "report_id": str(report_id),
            "evaluated_at": now().isoformat(),
        }
