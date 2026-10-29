"""Validate model output against frozen evidence and render it with server-owned values."""

from pydantic import ValidationError

from app.reports.grammar import EvidenceError, check_sentence, entities, free_text_issues, issue
from app.reports.schema import AnswerAnalysis, ReportAnalysis
from app.reports.tools import digest, limitations


def context(evidence, currency, exponent, language="zh", include_names=False):
    return {
        "evidence": {e["evidence_id"]: e for e in evidence},
        "entities": entities(evidence),
        "currency": currency,
        "exponent": exponent,
        "language": language,
        "include_names": include_names,
    }


def render(sentence, evidence, currency, exponent, language="zh", include_names=False):
    """Render a server-authored fact (deterministic summaries and fallbacks)."""
    issues, rendered = check_sentence(
        sentence, "fact", context(evidence, currency, exponent, language, include_names), True
    )
    if issues:
        raise EvidenceError(issues)
    return rendered


def schema_issues(error):
    return [
        issue(
            ".".join(str(part) for part in item["loc"]) or "$",
            "SCHEMA_" + item["type"].upper().replace(".", "_")[:40],
            item["msg"][:120],
        )
        for item in error.errors()[:8]
    ]


def check_scope(evidence, report_id, dataset_id, scope):
    for e in evidence:
        if (
            e["report_id"] != report_id
            or e["dataset_id"] != dataset_id
            or (scope is not None and e["scope"] != scope)
            or digest(e["payload"]) != e["result_hash"]
        ):
            raise EvidenceError([issue("evidence", "EVIDENCE_SCOPE")])


def _findings(items, ctx, prefix, language):
    issues, rendered = [], []
    for i, finding in enumerate(items):
        at = f"{prefix}[{i}]"
        found = free_text_issues(finding["title"], at + ".title", ctx, 60)
        found_obs, observation = check_sentence(
            finding["observation"], at + ".observation", ctx, True
        )
        supporting, hypotheses, hypothesis_text = [], [], []
        found += found_obs
        for j, sentence in enumerate(finding["supporting"]):
            problems, value = check_sentence(sentence, f"{at}.supporting[{j}]", ctx, True)
            found += problems
            supporting.append(value)
        for j, sentence in enumerate(finding["hypotheses"]):
            problems, value = check_sentence(sentence, f"{at}.hypotheses[{j}]", ctx, False)
            found += problems
            hypotheses.append(value)
        issues += found
        if found:
            continue
        hypothesis_text = [h["text"] for h in hypotheses]
        refs = observation["evidence_refs"] + [
            ref for item in supporting + hypotheses for ref in item["evidence_refs"]
        ]
        rendered.append(
            {
                "id": finding["id"],
                "topic": finding["topic"],
                "title": finding["title"],
                "kind": "observation",
                "observation": observation,
                "supporting": supporting,
                "hypotheses": hypothesis_text,
                "hypothesis_sentences": hypotheses,
                "evidence_refs": list(dict.fromkeys(refs)),
                "limitations": limitations(language),
            }
        )
    ids = [f["id"] for f in items]
    if len(set(ids)) != len(ids):
        issues.append(issue(prefix, "DUPLICATE_FINDING"))
    return issues, rendered


def _recommendations(items, finding_ids, findings, ctx, prefix):
    issues, rendered = [], []
    refs_by_finding = {f["id"]: f["evidence_refs"] for f in findings}
    for i, item in enumerate(items):
        at = f"{prefix}[{i}]"
        problems, action = check_sentence(item["action"], at + ".action", ctx, False)
        if not set(item["rationale_finding_ids"]) <= set(finding_ids):
            problems.append(issue(at + ".rationale_finding_ids", "FINDING_REFERENCE"))
        issues += problems
        if problems:
            continue
        refs = action["evidence_refs"] + [
            ref for fid in item["rationale_finding_ids"] for ref in refs_by_finding.get(fid, [])
        ]
        rendered.append(
            {
                **{k: item[k] for k in item if k != "action"},
                "action": action["text"],
                "action_sentence": action,
                "evidence_refs": list(dict.fromkeys(refs)),
            }
        )
    return issues, rendered


def validate_analysis(
    raw,
    evidence,
    report_id,
    dataset_id,
    currency,
    exponent,
    scope=None,
    language="zh",
    include_names=False,
):
    try:
        analysis = ReportAnalysis.model_validate(raw).model_dump(mode="json")
    except ValidationError as error:
        raise EvidenceError(schema_issues(error)) from None
    check_scope(evidence, report_id, dataset_id, scope)
    ctx = context(evidence, currency, exponent, language, include_names)
    issues, summary = [], []
    for i, sentence in enumerate(analysis["summary"]):
        problems, value = check_sentence(sentence, f"summary[{i}]", ctx, True)
        issues += problems
        summary.append(value)
    problems, findings = _findings(analysis["findings"], ctx, "findings", language)
    issues += problems
    ids = [f["id"] for f in analysis["findings"]]
    problems, recommendations = _recommendations(
        analysis["recommendations"], ids, findings, ctx, "recommendations"
    )
    issues += problems
    if issues:
        raise EvidenceError(issues)
    return {"summary": summary, "findings": findings, "recommendations": recommendations}


def validate_answer(
    raw,
    evidence,
    report_id,
    dataset_id,
    currency,
    exponent,
    scope=None,
    language="zh",
    include_names=False,
):
    try:
        analysis = AnswerAnalysis.model_validate(raw).model_dump(mode="json")
    except ValidationError as error:
        raise EvidenceError(schema_issues(error)) from None
    check_scope(evidence, report_id, dataset_id, scope)
    ctx = context(evidence, currency, exponent, language, include_names)
    issues, answer = [], []
    for i, sentence in enumerate(analysis["answer"]):
        problems, value = check_sentence(sentence, f"answer[{i}]", ctx, True)
        issues += problems
        answer.append(value)
    problems, findings = _findings(analysis["findings"], ctx, "findings", language)
    issues += problems
    ids = [f["id"] for f in analysis["findings"]]
    problems, recommendations = _recommendations(
        analysis["recommendations"], ids, findings, ctx, "recommendations"
    )
    issues += problems
    clarify = None
    if analysis["clarify"] is not None:
        problems, clarify = check_sentence(analysis["clarify"], "clarify", ctx, False)
        issues += problems
    for i, option in enumerate(analysis["options"]):
        issues += free_text_issues(option, f"options[{i}]", ctx, 40)
    query = analysis["suggested_query"]
    if query is not None:
        from datetime import date

        start, end = date.fromisoformat(query["start"]), date.fromisoformat(query["end_exclusive"])
        if not 1 <= (end - start).days <= 366 or any(not s or len(s) > 128 for s in query["skus"]):
            issues.append(issue("suggested_query", "INVALID_QUERY"))
    if issues:
        raise EvidenceError(issues)
    return {
        "kind": analysis["kind"],
        "answer": answer,
        "findings": findings,
        "recommendations": recommendations,
        "clarify": clarify,
        "options": analysis["options"],
        "suggested_query": query,
        "summary": answer,
    }
