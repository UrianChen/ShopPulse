import re
from decimal import Decimal, localcontext

from app.reports.schema import Analysis
from app.reports.tools import LIMITATIONS, digest, metric_facts


def render(sentence, evidence, currency, exponent):
    binding = sentence["bindings"]["value"]
    ev = next(e for e in evidence if e["evidence_id"] == binding["evidence_id"])
    value = ev["payload"]
    for part in binding["path"].split("."):
        value = value[part]
    with localcontext() as context:
        context.prec = 70
        amount = Decimal(value["value"])
        formatted = (
            f"{currency} {amount / (Decimal(10) ** exponent):,.{exponent}f}"
            if binding["format"] == "money"
            else f"{amount * 100:,.2f}%"
            if binding["format"] == "percent"
            else f"{amount:,.0f}"
        )
    if value["quality"] == "estimated":
        formatted += "（估算）"
    return {
        **sentence,
        "text": sentence["text_template"].replace("{{value}}", formatted),
        "evidence_refs": [binding["evidence_id"]],
    }


def validate_analysis(raw, evidence, report_id, dataset_id, currency, exponent, scope=None):
    analysis = Analysis.model_validate(raw).model_dump()
    ids = {e["evidence_id"] for e in evidence}
    if any(
        e["report_id"] != report_id
        or e["dataset_id"] != dataset_id
        or (scope is not None and e["scope"] != scope)
        or digest(e["payload"]) != e["result_hash"]
        for e in evidence
    ):
        raise ValueError("EVIDENCE_SCOPE")
    allowed = metric_facts(evidence)
    sentences = analysis["summary"] + [f["observation"] for f in analysis["findings"]]
    # Facts are selected from server-authored grammar, not arbitrary prose with appended citations.
    if any(sentence not in allowed for sentence in sentences):
        raise ValueError("UNBOUND_FACT")
    finding_ids = [f["id"] for f in analysis["findings"]]
    if len(set(finding_ids)) != len(finding_ids):
        raise ValueError("DUPLICATE_FINDING")
    free_text = []
    for finding in analysis["findings"]:
        if finding["title"] not in {"经营观察", "退款观察", "成本观察", "商品观察", "周期观察"}:
            raise ValueError("UNVERIFIED_TITLE")
        refs = set(finding["evidence_refs"])
        bound = finding["observation"]["bindings"]["value"]["evidence_id"]
        if not refs <= ids or bound not in refs:
            raise ValueError("EVIDENCE_REFERENCE")
        free_text += [finding["title"], *finding["hypotheses"], *finding["limitations"]]
        finding["kind"] = "observation"
        finding["observation"] = render(finding["observation"], evidence, currency, exponent)
        finding["limitations"] = list(dict.fromkeys(finding["limitations"] + LIMITATIONS))
    for recommendation in analysis["recommendations"]:
        if not set(recommendation["rationale_finding_ids"]) <= set(finding_ids):
            raise ValueError("FINDING_REFERENCE")
        free_text.append(recommendation["action"])
    for text in free_text:
        # Numbers, SKUs and definitive claims have no free-text channel. Actions are proposals.
        if (
            len(text) > 300
            or any(character.isnumeric() for character in text)
            or re.search(
                r"[两半倍%％<>]|https?://|SKU|保证|必然|确定导致|"
                r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
                r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
                r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
                r"million|billion|percent|double|triple|half|quarter)\b",
                text,
                re.I,
            )
        ):
            raise ValueError("UNBOUND_NUMBER_OR_CLAIM")
    analysis["summary"] = [render(s, evidence, currency, exponent) for s in analysis["summary"]]
    return analysis
