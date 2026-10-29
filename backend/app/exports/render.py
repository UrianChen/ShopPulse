"""One frozen report document, escaped offline HTML / Markdown / PDF presentations.

Headings, labels and units follow the report's own language (``content["language"]``), so an
English report exports in English and a Chinese report in Chinese. Business data such as product
names and merchant notes keep their original text.
"""

import base64
import io
import json
import re
import zipfile
from decimal import Decimal, localcontext
from html import escape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from app.reports.grammar import LABELS

FONT = Path(__file__).resolve().parents[2] / "assets/fonts/NotoSansSC.ttf"
TEXT = {
    "zh": {
        "html_lang": "zh-CN",
        "doc_title": "ShopPulse 报告",
        "kind": "冻结经营报告",
        "revision": "修订",
        "report": "报告",
        "report_id": "报告 ID",
        "payment_date": "支付日期",
        "timezone": "时区",
        "currency": "币种",
        "mode": "模式",
        "engine": "引擎",
        "dataset": "数据版本",
        "as_of": "截止",
        "model_notice": "模型分析未通过或不可用，保留确定性摘要。",
        "overview": "经营概览",
        "evidence": "证据",
        "metric": "指标",
        "current": "本期",
        "previous": "比较期",
        "not_selected": "未选择",
        "charts_heading": "趋势与销售贡献",
        "charts": "图表",
        "trend_alt": "净销售额趋势",
        "contribution_alt": "销售贡献",
        "products_heading": "商品表现（净销售额前十项）",
        "products": "商品表现",
        "sku_product": "SKU / 商品",
        "net_sales": "净销售额",
        "gross_profit": "商品毛利",
        "paid_units": "支付件数",
        "unmapped": "未映射",
        "anomalies": "异常与限制",
        "values": "实际值与阈值：",
        "flags": "质量标记：",
        "none": "无",
        "findings": "经营观察与行动建议",
        "recommendations": "建议",
        "hypothesis": "待验证假设：",
        "priority": "优先级",
        "effort": "工作量",
        "verification": "验证指标",
        "review": "复查",
        "followups": "上期建议跟进",
        "recommendation": "建议",
        "baseline": "提出时",
        "result": "结论",
        "notes": "商家备注",
        "appendix": "证据附录",
        "appendix_text": "证据绑定本报告范围。完整工具结果保存在应用中；"
        "HTML 中可展开查看，Markdown 包另含 evidence.json。",
        "appendix_md": "完整证据见同包 evidence.json。",
        "scope": "范围",
        "full_evidence": "完整计算证据",
        "unavailable": "不可用（{}）",
        "insufficient": "数据不足",
        "estimated": "（估算）",
        "chart_trend": "净销售额趋势（覆盖不完整处断开）",
        "chart_empty": "本期无可比较的销售贡献数据",
        "separator": "：",
        "values_map": {
            "high": "高",
            "medium": "中",
            "low": "低",
            "small": "小",
            "large": "大",
            "next_week": "下周",
            "next_month": "下月",
        },
    },
    "en": {
        "html_lang": "en",
        "doc_title": "ShopPulse report",
        "kind": "Frozen business report",
        "revision": "Revision",
        "report": "Report",
        "report_id": "Report ID",
        "payment_date": "payment date",
        "timezone": "Time zone",
        "currency": "Currency",
        "mode": "Mode",
        "engine": "Engine",
        "dataset": "Dataset",
        "as_of": "Data as of",
        "model_notice": "Model analysis failed or was unavailable; the calculated summary is kept.",
        "overview": "Overview",
        "evidence": "Evidence",
        "metric": "Metric",
        "current": "Current",
        "previous": "Comparison",
        "not_selected": "Not selected",
        "charts_heading": "Trend and sales contribution",
        "charts": "Charts",
        "trend_alt": "Net sales trend",
        "contribution_alt": "Sales contribution",
        "products_heading": "Products (top ten by net sales)",
        "products": "Products",
        "sku_product": "SKU / Product",
        "net_sales": "Net sales",
        "gross_profit": "Gross profit",
        "paid_units": "Paid units",
        "unmapped": "Unmapped",
        "anomalies": "Anomalies and limitations",
        "values": "Values and thresholds: ",
        "flags": "Quality flags: ",
        "none": "None",
        "findings": "Findings and recommendations",
        "recommendations": "Recommendations",
        "hypothesis": "Hypothesis to verify: ",
        "priority": "Priority",
        "effort": "Effort",
        "verification": "Verification metric",
        "review": "Review",
        "followups": "Earlier recommendations",
        "recommendation": "Recommendation",
        "baseline": "When proposed",
        "result": "Result",
        "notes": "Merchant notes",
        "appendix": "Evidence appendix",
        "appendix_text": "Evidence is bound to this report's scope. Full tool results stay in "
        "the app; expand them below in HTML, and the Markdown package also contains "
        "evidence.json.",
        "appendix_md": "Full evidence is in evidence.json in this package.",
        "scope": "Scope",
        "full_evidence": "Full calculation evidence",
        "unavailable": "Unavailable ({})",
        "insufficient": "insufficient data",
        "estimated": " (est.)",
        "chart_trend": "Net sales trend (gaps where coverage is incomplete)",
        "chart_empty": "No comparable sales contribution data for this period",
        "separator": ": ",
        "values_map": {
            "high": "High",
            "medium": "Medium",
            "low": "Low",
            "small": "Small",
            "large": "Large",
            "next_week": "Next week",
            "next_month": "Next month",
        },
    },
}
CSS = """
@page { size:A4; margin:17mm 15mm 18mm; }
*{box-sizing:border-box}body{font-family:ReportFont,sans-serif;color:#243f35;font-size:12px;
line-height:1.65;max-width:960px;margin:32px auto;padding:0 20px;overflow-wrap:anywhere}
h1{font-size:27px;line-height:1.35}
h2{font-size:19px;margin:25px 0 12px;border-bottom:2px solid #92ac78;
padding-bottom:6px;break-after:avoid}h3{font-size:14px;break-after:avoid}.meta{color:#66765d}
table{border-collapse:collapse;width:100%;font-size:11px;table-layout:fixed;margin:12px 0}
th,td{padding:7px 8px;text-align:left;border-bottom:1px solid #dfe5da;vertical-align:top}
th{background:#edf2e6}thead{display:table-header-group}tr,td{break-inside:avoid;page-break-inside:avoid}
.chart{break-inside:avoid;margin:18px 0}.chart svg{width:100%;height:auto}
.notice{padding:12px;background:#fff5e3;border-left:3px solid #c3a463}
.fact{padding:8px 12px;background:#f3f6ef}
.evidence{font-size:9px;color:#67755f;break-inside:avoid}
pre{white-space:pre-wrap;font-size:9px}a{color:inherit}li{margin:5px 0}
@media print{body{margin:0;padding:0;max-width:none}
details{display:none}h1{font-size:25px}}
"""


def language_of(content):
    return "en" if content.get("language") == "en" else "zh"


def label(domain, key, language):
    value = LABELS[domain][language].get(key, key)
    return value[:1].upper() + value[1:] if language == "en" else value


def money(metric, result, language="zh"):
    words = TEXT[language]
    if metric["value"] is None:
        reason = metric.get("unavailable_reason") or words["insufficient"]
        return words["unavailable"].format(reason)
    with localcontext() as ctx:
        ctx.prec = 70
        value = Decimal(metric["value"])
        unit = metric["unit"]
        exponent = result["currency_exponent"]
        text = (
            f"{result['currency']} {value / Decimal(10) ** exponent:,.{exponent}f}"
            if unit == "minor_currency"
            else f"{value * 100:,.2f}%"
            if unit == "ratio"
            else f"{value:,.0f}"
        )
    return text + (words["estimated"] if metric["quality"] == "estimated" else "")


def chart(result, kind, language="zh"):
    # Coordinates are derived from code-computed metrics; labels retain exact decimal formatting.
    words = TEXT[language]
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 260" role="img">',
        '<rect width="720" height="260" fill="#f5f8f1"/>',
    ]
    if kind == "trend":
        points = result["trend"]
        values = [Decimal(p["metrics"]["net_sales"]["value"] or 0) for p in points]
        low, high = min(values + [Decimal(0)]), max(values + [Decimal(1)])
        path = []
        for i, (p, value) in enumerate(zip(points, values, strict=True)):
            x, y = (
                48 + 620 * i / max(1, len(points) - 1),
                210 - float((value - low) / (high - low)) * 165,
            )
            if p["metrics"]["net_sales"]["value"] is None or not p["coverage_complete"]:
                if path:
                    svg.append(
                        '<polyline fill="none" stroke="#52735c" stroke-width="2" points="'
                        + " ".join(path)
                        + '"/>'
                    )
                path = []
                continue
            path.append(f"{x:.2f},{y:.2f}")
        if path:
            svg.append(
                '<polyline fill="none" stroke="#52735c" stroke-width="2" points="'
                + " ".join(path)
                + '"/>'
            )
        for x, text in [
            (40, points[0]["start"] if points else ""),
            (570, points[-1]["start"] if points else ""),
        ]:
            svg.append(f'<text x="{x}" y="240" font-size="12">{escape(str(text))}</text>')
        svg.append(f'<text x="40" y="24" font-size="14">{escape(words["chart_trend"])}</text>')
    else:
        data = result["contributions"]
        rows = (data.get("gainers", [])[:3] + data.get("decliners", [])[:3])[:6]
        if not data.get("available") or not rows:
            svg.append(f'<text x="40" y="90">{escape(words["chart_empty"])}</text>')
        else:
            maximum = max(abs(Decimal(r["sales_contribution_minor"])) for r in rows) or Decimal(1)
            for i, row in enumerate(rows):
                delta = Decimal(row["sales_contribution_minor"])
                y = 25 + i * 36
                name = str(row.get("sku") or words["unmapped"])[:18]
                svg.append(f'<text x="14" y="{y + 14}" font-size="11">{escape(name)}</text>')
                width = float(abs(delta) / maximum) * 370
                svg.append(
                    f'<rect x="170" y="{y}" width="{width:.2f}" height="19" '
                    f'fill="{"#92ac78" if delta >= 0 else "#bc917e"}"/>'
                )
                amount = money(
                    {"value": str(delta), "unit": "minor_currency", "quality": "confirmed"},
                    result,
                    language,
                )
                svg.append(f'<text x="550" y="{y + 14}" font-size="11">{escape(amount)}</text>')
    return "".join(svg) + "</svg>"


def font_css(text):
    font = TTFont(FONT)
    options = subset.Options()
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    worker = subset.Subsetter(options=options)
    worker.populate(text=text)
    worker.subset(font)
    # Subset first: instantiating the complete 65k-glyph variable font is needlessly expensive.
    if "fvar" in font:
        font = instantiateVariableFont(font, {"wght": 400}, inplace=True)
    for record in font["name"].names:
        if record.nameID in {1, 3, 4, 6}:
            record.string = "ShopPulseReportFont".encode(record.getEncoding())
    stream = io.BytesIO()
    font.save(stream)
    font.close()
    data = base64.b64encode(stream.getvalue()).decode()
    return (
        "@font-face{font-family:ReportFont;src:url(data:font/ttf;base64,"
        + data
        + ") format('truetype');}"
    )


def metric_label(item, language):
    return label("metric", item["key"], language) if language == "en" else item["label"]


def recommendation_meta(item, language):
    words = TEXT[language]
    values = words["values_map"]
    return " · ".join(
        [
            f"{words['priority']} {values.get(item['priority'], item['priority'])}",
            f"{words['effort']} {values.get(item['effort'], item['effort'])}",
            f"{words['verification']} {label('metric', item['verification_metric'], language)}",
            f"{words['review']} "
            + values.get(item["suggested_review_window"], item["suggested_review_window"]),
        ]
    )


def document(content, evidence):
    result = content["metrics"]
    language = language_of(content)
    words = TEXT[language]
    query = result["query"]
    parts = [
        f"<h1>{escape(content['title'])}</h1>",
        f'<p class="meta">ShopPulse · {words["kind"]} · {words["revision"]} '
        + str(content["revision"])
        + f"<br>{words['report_id']} "
        + escape(content["report_id"])
        + "<br>"
        + escape(query["start"])
        + f" ≤ {words['payment_date']} &lt; "
        + escape(query["end_exclusive"])
        + f"<br>{words['timezone']} "
        + escape(result["timezone"])
        + f" · {words['currency']} "
        + escape(result["currency"])
        + f"<br>{words['mode']} "
        + escape(content["generation_mode"])
        + f" · {words['engine']} "
        + escape(result["engine_version"])
        + f"<br>{words['dataset']} "
        + escape(result["dataset_id"])
        + f" · {words['as_of']} "
        + escape(result["source_as_of"])
        + "</p>",
    ]
    if content.get("model_error_code") not in (None, "NO_MODEL"):
        parts.append(f'<p class="notice">{words["model_notice"]}</p>')
    parts.append(f"<h2>{words['overview']}</h2>")
    for line in content["summary"]:
        parts.append(
            '<p class="fact">'
            + escape(line["text"])
            + f'<br><span class="evidence">{words["evidence"]} '
            + escape(", ".join(line["evidence_refs"]))
            + "</span></p>"
        )
    parts.append(
        f"<table><thead><tr><th>{words['metric']}</th><th>{words['current']}</th>"
        f"<th>{words['previous']}</th></tr></thead><tbody>"
    )
    for item in content["metric_cards"]:
        previous = result["previous"]
        parts.append(
            "<tr><td>"
            + escape(metric_label(item, language))
            + "</td><td>"
            + escape(money(item["metric"], result, language))
            + "</td><td>"
            + escape(
                money(previous["metrics"][item["key"]], result, language)
                if previous
                else words["not_selected"]
            )
            + "</td></tr>"
        )
    parts.append(f"</tbody></table><h2>{words['charts_heading']}</h2>")
    for kind in ("trend", "contributions"):
        parts.append('<div class="chart">' + chart(result, kind, language) + "</div>")
    parts.append(
        f"<h2>{words['products_heading']}</h2><table><thead><tr>"
        f"<th>{words['sku_product']}</th><th>{words['net_sales']}</th>"
        f"<th>{words['gross_profit']}</th><th>{words['paid_units']}</th></tr></thead><tbody>"
    )
    for row in content["products"]:
        parts.append(
            "<tr><td>"
            + escape(str(row["sku"] or words["unmapped"]))
            + "<br>"
            + escape(row["product_name"])
            + "</td>"
            + "".join(
                "<td>" + escape(money(row["current"]["metrics"][key], result, language)) + "</td>"
                for key in ("net_sales", "gross_profit", "paid_units")
            )
            + "</tr>"
        )
    parts.append(f"</tbody></table><h2>{words['anomalies']}</h2>")
    for item in content["anomalies"]["checks"]:
        parts.append(
            "<h3>"
            + escape(label("rule", item["code"], language))
            + words["separator"]
            + escape(label("rule_state", item["state"], language))
            + "</h3><p>"
            + escape(item["limitation"])
            + f'</p><p class="evidence">{words["values"]}'
            + escape(json.dumps(item["values"], ensure_ascii=False))
            + "</p>"
        )
    flags = ", ".join(label("warning", w, language) for w in content["warnings"])
    parts.append(
        f'<p class="notice">{words["flags"]}' + escape(flags or words["none"]) + "</p><ul>"
    )
    parts.extend("<li>" + escape(item) + "</li>" for item in content["limitations"])
    parts.append(f"</ul><h2>{words['findings']}</h2>")
    for finding in content["findings"]:
        parts.append(
            "<h3>"
            + escape(finding["title"])
            + "</h3><p>"
            + escape(finding["observation"]["text"])
            + "</p>"
        )
        parts.extend("<p>" + escape(s["text"]) + "</p>" for s in finding.get("supporting") or [])
        parts.extend(
            f"<p>{words['hypothesis']}" + escape(s) + "</p>" for s in finding["hypotheses"]
        )
        parts.append(
            f'<p class="evidence">{words["evidence"]} '
            + escape(", ".join(finding["evidence_refs"]))
            + "</p>"
        )
    for item in content["recommendations"]:
        parts.append(
            '<p class="fact">'
            + escape(item["action"])
            + "<br>"
            + escape(recommendation_meta(item, language))
            + "</p>"
        )
    if content.get("action_followups"):
        parts.append(
            f"<h2>{words['followups']}</h2><table><thead><tr>"
            + "".join(
                f"<th>{words[key]}</th>"
                for key in ("recommendation", "verification", "baseline", "current", "result")
            )
            + "</tr></thead><tbody>"
        )
        for item in content["action_followups"]:
            parts.append(
                "<tr><td>"
                + "</td><td>".join(escape(v) for v in followup_row(item, result, language))
                + "</td></tr>"
            )
        parts.append("</tbody></table>")
    if content.get("merchant_notes"):
        parts.append(f"<h2>{words['notes']}</h2><ul>")
        parts.extend(
            "<li>" + escape(note_line(n, language)) + "</li>" for n in content["merchant_notes"]
        )
        parts.append("</ul>")
    parts.append(f"<h2>{words['appendix']}</h2><p>{escape(words['appendix_text'])}</p>")
    for ev in evidence:
        parts.append(
            '<p class="evidence"><b>'
            + escape(ev["tool"])
            + "</b><br>ID "
            + escape(ev["evidence_id"])
            + "<br>SHA-256 "
            + escape(ev["result_hash"])
            + f"<br>{words['scope']} "
            + escape(json.dumps(ev["scope"], ensure_ascii=False))
            + "</p>"
        )
    parts.append(
        f"<details><summary>{words['full_evidence']}</summary><pre>"
        + escape(json.dumps(evidence, ensure_ascii=False, indent=2))
        + "</pre></details>"
    )
    return "".join(parts)


def followup_row(item, result, language="zh"):
    return [
        item["action_text"],
        label("metric", item["verification_metric"], language),
        money(item["baseline"], result, language) if item.get("baseline") else "—",
        money(item["current"], result, language) if item.get("current") else "—",
        label("followup", item["state"], language),
    ]


def note_line(note, language="zh"):
    kind = label("note_kind", note["kind"], language)
    return f"{note['start']} – {note['end_exclusive']} · {kind} · {note['text']}"


def html_document(content, evidence):
    body = document(content, evidence)
    words = TEXT[language_of(content)]
    # Only a server-authored template, escaped data and data-embedded font; no scripts or URLs.
    text = re.sub("<[^>]+>", "", body)
    return (
        f'<!doctype html><html lang="{words["html_lang"]}"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src '
        "'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; base-uri 'none'; "
        "form-action 'none'\"><title>"
        + escape(words["doc_title"])
        + "</title><style>"
        + CSS
        + font_css(text)
        + "</style><body>"
        + body
        + "</body></html>"
    )


def markdown_zip(content, evidence):
    result = content["metrics"]
    language = language_of(content)
    words = TEXT[language]

    def safe(value):
        return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", escape(str(value))).replace("\n", " ")

    lines = [
        "# " + safe(content["title"]),
        "",
        f"{words['report']} "
        + content["report_id"]
        + f" · {words['revision']} "
        + str(content["revision"]),
        "",
        safe(json.dumps(result["query"], ensure_ascii=False)),
        "",
        f"{words['mode']} " + safe(content["generation_mode"]),
        "",
        f"{words['currency']} "
        + result["currency"]
        + f" · {words['timezone']} "
        + result["timezone"],
        "",
        f"## {words['overview']}",
        "",
    ]
    for s in content["summary"]:
        lines += [
            safe(s["text"]),
            "",
            words["evidence"] + words["separator"] + ", ".join(s["evidence_refs"]),
            "",
        ]
    lines += [f"| {words['metric']} | {words['current']} | {words['previous']} |"]
    lines += ["| --- | --- | --- |"]
    for c in content["metric_cards"]:
        previous = (
            money(result["previous"]["metrics"][c["key"]], result, language)
            if result["previous"]
            else words["not_selected"]
        )
        lines.append(
            "| "
            + safe(metric_label(c, language))
            + " | "
            + safe(money(c["metric"], result, language))
            + " | "
            + safe(previous)
            + " |"
        )
    lines += [
        "",
        f"## {words['charts']}",
        "",
        f"![{words['trend_alt']}](trend.svg)",
        "",
        f"![{words['contribution_alt']}](contributions.svg)",
        "",
        f"## {words['products']}",
        "",
        f"| {words['sku_product']} | {words['net_sales']} | {words['gross_profit']} "
        f"| {words['paid_units']} |",
        "| --- | --- | --- | --- |",
    ]
    for row in content["products"]:
        lines.append(
            "| "
            + safe(str(row["sku"] or words["unmapped"]) + " / " + row["product_name"])
            + " | "
            + " | ".join(
                safe(money(row["current"]["metrics"][k], result, language))
                for k in ("net_sales", "gross_profit", "paid_units")
            )
            + " |"
        )
    lines += ["", f"## {words['anomalies']}", ""]
    for c in content["anomalies"]["checks"]:
        lines += [
            "### "
            + label("rule", c["code"], language)
            + words["separator"]
            + label("rule_state", c["state"], language),
            "",
            safe(c["limitation"]),
            "",
            safe(json.dumps(c["values"], ensure_ascii=False)),
            "",
        ]
    flags = ", ".join(label("warning", w, language) for w in content["warnings"])
    lines += [safe(s) for s in content["limitations"]] + [
        "",
        words["flags"] + safe(flags or words["none"]),
        "",
        f"## {words['recommendations']}",
        "",
    ]
    for f in content["findings"]:
        lines += [
            safe(f["observation"]["text"]),
            "",
            *[safe(s["text"]) for s in f.get("supporting") or []],
            *[words["hypothesis"] + safe(h) for h in f["hypotheses"]],
            "",
        ]
    for a in content["recommendations"]:
        lines += [safe(a["action"]), "", safe(recommendation_meta(a, language)), ""]
    if content.get("action_followups"):
        headers = [
            words[k] for k in ("recommendation", "verification", "baseline", "current", "result")
        ]
        lines += [f"## {words['followups']}", "", "| " + " | ".join(headers) + " |"]
        lines.append("| --- | --- | --- | --- | --- |")
        for item in content["action_followups"]:
            row = followup_row(item, result, language)
            lines.append("| " + " | ".join(safe(v) for v in row) + " |")
        lines.append("")
    if content.get("merchant_notes"):
        lines += [f"## {words['notes']}", ""]
        lines += ["- " + safe(note_line(n, language)) for n in content["merchant_notes"]]
        lines.append("")
    lines += [f"## {words['appendix']}", "", words["appendix_md"], ""]
    for ev in evidence:
        lines += [safe(ev["tool"]) + ": " + ev["evidence_id"] + " / " + ev["result_hash"], ""]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.md", "\n".join(lines))
        archive.writestr("evidence.json", json.dumps(evidence, ensure_ascii=False, indent=2))
        for kind in ("trend", "contributions"):
            archive.writestr(kind + ".svg", chart(result, kind, language))
    return output.getvalue()
