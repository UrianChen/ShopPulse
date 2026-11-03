"""Validate model output against frozen evidence and render it with server-owned values."""

import re
from decimal import Decimal

from pydantic import ValidationError

from app.reports.grammar import (
    EvidenceError,
    check_sentence,
    entities,
    free_text_issues,
    issue,
    rule_for,
    walk,
)
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
        "derived": {},
        "verdicts": verdicts(evidence),
    }


def verdicts(evidence):
    """Latest verdict per hypothesis id (later waves and reruns replace earlier ones)."""
    found = {}
    for ev in evidence:
        if ev["tool"] == "test_hypothesis":
            found[ev["payload"]["id"]] = ev
    return found


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


def hypothesis_refs(ids, at, ctx, state):
    """Check hypothesis ids against server verdicts; return (issues, rendered references)."""
    issues, rendered = [], []
    for index, hypothesis_id in enumerate(ids):
        ev = ctx["verdicts"].get(hypothesis_id)
        if ev is None:
            issues.append(issue(f"{at}[{index}]", "UNKNOWN_HYPOTHESIS"))
        elif ev["payload"]["state"] != state:
            issues.append(
                issue(
                    f"{at}[{index}]",
                    "HYPOTHESIS_NOT_" + state.upper(),
                    f"the server judged it {ev['payload']['state']}",
                )
            )
        else:
            rendered.append(
                {
                    "id": hypothesis_id,
                    "text": ev["payload"]["statement"],
                    "state": state,
                    "quality": ev["payload"]["quality"],
                    "evidence_id": ev["evidence_id"],
                    "test_evidence_id": ev["payload"]["test_evidence_id"],
                }
            )
    if len(set(ids)) != len(ids):
        issues.append(issue(at, "DUPLICATE_HYPOTHESIS"))
    return issues, rendered


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
        problems, supported = hypothesis_refs(
            finding.get("hypothesis_ids") or [], at + ".hypothesis_ids", ctx, "supported"
        )
        found += problems
        issues += found
        if found:
            continue
        hypothesis_text = [h["text"] for h in hypotheses]
        refs = (
            observation["evidence_refs"]
            + [ref for item in supporting + hypotheses for ref in item["evidence_refs"]]
            + [ref for item in supported for ref in (item["evidence_id"], item["test_evidence_id"])]
        )
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
                "supported_hypotheses": supported,
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
    ruled_out = []
    for i, item in enumerate(analysis["ruled_out"]):
        at = f"ruled_out[{i}]"
        problems, refs = hypothesis_refs(
            [item["hypothesis_id"]], at + ".hypothesis_id", ctx, "refuted"
        )
        found, sentence = check_sentence(item["sentence"], at + ".sentence", ctx, False)
        problems += found
        issues += problems
        if not problems:
            ruled_out.append(
                {
                    "hypothesis_id": item["hypothesis_id"],
                    "statement": refs[0]["text"],
                    "text": sentence["text"],
                    "sentence": sentence,
                    "evidence_refs": list(
                        dict.fromkeys(
                            [refs[0]["evidence_id"], refs[0]["test_evidence_id"]]
                            + sentence["evidence_refs"]
                        )
                    ),
                }
            )
    if len({item["hypothesis_id"] for item in analysis["ruled_out"]}) != len(analysis["ruled_out"]):
        issues.append(issue("ruled_out", "DUPLICATE_HYPOTHESIS"))
    if issues:
        raise EvidenceError(issues)
    return {
        "summary": summary,
        "findings": findings,
        "recommendations": recommendations,
        "ruled_out": ruled_out,
        "derived_evidence": list(ctx["derived"].values()),
    }


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
        "derived_evidence": list(ctx["derived"].values()),
    }


# ----------------------------------------------------------------- deterministic review (lint)
DOWN_WORDS = (
    r"下降|减少|下滑|回落|降低|走低|萎缩|缩水|下跌|\b(?:declin\w*|drop\w*|fell|fall\w*|"
    r"decreas\w*|lower|down|shrank|shrink\w*)\b"
)
UP_WORDS = (
    r"上升|增长|增加|提升|上涨|走高|扩大|攀升|\b(?:ris\w*|rose|grow\w*|grew|increas\w*|"
    r"higher|up|gain\w*|climb\w*)\b"
)
DOWN = re.compile(DOWN_WORDS, re.I)
UP = re.compile(UP_WORDS, re.I)
# A negation right before a direction word ("没有下降", "未出现增长", "did not decline", "no longer
# rising"), with at most a few filler words between. "不断增长" and "未来增长" do not match: the
# character after the negation must be a filler or the direction word itself.
NEGATION = (
    r"(?:(?:并未|并没有|并无|没有|未曾|未见|不再|并不|未|没|不|无)"
    r"(?:出现|发生|见|再|继续|持续|明显|显著|进一步|大幅|任何)*"
    r"|(?:\b(?:not|no|never|without)|n't)\s+"
    r"(?:(?:longer|further|any|a|an|yet|been|see|seen|show|shown|significantly|materially|"
    r"much)\s+){0,3})"
)
NEGATED_DOWN = re.compile(f"{NEGATION}(?:{DOWN_WORDS})", re.I)
NEGATED_UP = re.compile(f"{NEGATION}(?:{UP_WORDS})", re.I)
SIGNED_KINDS = {"delta", "signed_ratio", "pp", "signed_money"}
TOPIC_METRICS = {
    "sales": {"net_sales", "paid_orders"},
    "refund": {"refund_amount_rate"},
    "cost": {"gross_profit"},
    "product": {"net_sales", "gross_profit", "paid_orders", "refund_amount_rate"},
    "period": {"net_sales", "paid_orders"},
}


def _signs(sentence, by_id):
    signs = []
    for binding in sentence["bindings"]:
        ev = by_id.get(binding["evidence_id"])
        rule = rule_for(ev["tool"], binding["path"]) if ev else None
        if rule is None:
            continue
        derive = binding.get("derive")
        if derive is not None and derive["op"] != "diff":
            continue
        if derive is None and rule[0] not in SIGNED_KINDS:
            continue
        try:
            if derive is not None:
                from app.reports.derive import compute, operand

                other = by_id[derive["b"]["evidence_id"]]
                value = Decimal(
                    compute(
                        "diff",
                        operand(ev, binding["path"]),
                        operand(other, derive["b"]["path"]),
                    )["value"]
                )
            else:
                value = Decimal(str(walk(ev["payload"], binding["path"])))
        except (ArithmeticError, KeyError, TypeError, ValueError):
            continue
        if value != 0:
            signs.append(value > 0)
    return signs


def _sentences(raw):
    for i, sentence in enumerate(raw.get("summary") or raw.get("answer") or []):
        key = "summary" if raw.get("summary") else "answer"
        yield f"{key}[{i}]", sentence, None
    for i, finding in enumerate(raw.get("findings") or []):
        yield f"findings[{i}].observation", finding["observation"], i
        for j, sentence in enumerate(finding["supporting"]):
            yield f"findings[{i}].supporting[{j}]", sentence, i
        for j, sentence in enumerate(finding["hypotheses"]):
            yield f"findings[{i}].hypotheses[{j}]", sentence, i


def direction(template):
    """The direction a sentence claims: "down", "up", or None when it claims none or both."""
    text = re.sub(r"\{\{[a-z0-9_]+\}\}", " ", template)
    # "Did not decline" claims not-down, which a negative change contradicts just as it does "rose".
    up, down = bool(NEGATED_DOWN.search(text)), bool(NEGATED_UP.search(text))
    text = NEGATED_UP.sub(" ", NEGATED_DOWN.sub(" ", text))
    down, up = down or bool(DOWN.search(text)), up or bool(UP.search(text))
    return None if down == up else "down" if down else "up"


def direction_mismatch(template, signs):
    """Does the wording contradict the sign (True = positive) of every bound change?"""
    claim = direction(template) if signs else None
    return (claim == "down" and all(signs)) or (claim == "up" and not any(signs))


def lint(raw, evidence):
    """Deterministic review of a validated reply. Issues are soft: they trigger one repair."""
    by_id = {e["evidence_id"]: e for e in evidence}
    found = []
    for at, sentence, _ in _sentences(raw):
        if direction_mismatch(sentence["template"], _signs(sentence, by_id)):
            found.append(
                issue(
                    at,
                    "DIRECTION_MISMATCH",
                    "the wording says the opposite of the bound change's sign",
                )
            )
    topics = {f["id"]: f["topic"] for f in raw.get("findings") or []}
    for i, item in enumerate(raw.get("recommendations") or []):
        allowed = set()
        for finding_id in item["rationale_finding_ids"]:
            allowed |= TOPIC_METRICS.get(topics.get(finding_id), {item["verification_metric"]})
        if allowed and item["verification_metric"] not in allowed:
            found.append(
                issue(
                    f"recommendations[{i}].verification_metric",
                    "NO_VERIFICATION",
                    "verification metric does not measure the linked findings; use one of "
                    + ", ".join(sorted(allowed)),
                )
            )
    names = entities(evidence)
    for at, sentence, finding_index in _sentences(raw):
        if finding_index is None:
            continue
        for binding in sentence["bindings"]:
            ev = by_id.get(binding["evidence_id"])
            if not ev or ev["tool"] != "get_merchant_notes" or binding["format"] != "note":
                continue
            try:
                note = str(walk(ev["payload"], binding["path"])).lower()
            except (KeyError, TypeError):
                continue
            mentioned = {name for name in names if name in note}
            if not mentioned:
                continue
            finding = raw["findings"][finding_index]
            bound = set()
            for other in [finding["observation"], *finding["supporting"], *finding["hypotheses"]]:
                for b in other["bindings"]:
                    other_ev = by_id.get(b["evidence_id"])
                    if other_ev and b["format"] == "entity":
                        try:
                            bound.add(str(walk(other_ev["payload"], b["path"])).lower())
                        except (KeyError, TypeError):
                            pass
            if not bound & mentioned:
                found.append(
                    issue(
                        at,
                        "WEAK_NOTE_LINK",
                        "the note names other products than this finding; cite it where it "
                        "applies or drop it",
                    )
                )
    return found[:8]
