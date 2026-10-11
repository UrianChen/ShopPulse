"""One frozen report document, escaped offline HTML / Markdown / PDF presentations."""

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

FONT = Path(__file__).resolve().parents[2] / "assets/fonts/NotoSansSC.ttf"
RULES = {
    "SALES_CHANGE": "净销售额变化",
    "HIGH_REFUND": "退款占比",
    "MARGIN_DROP": "毛利率下降",
    "NEGATIVE_PROFIT": "负毛利商品",
    "CONCENTRATION": "销售集中度",
    "DAILY_MAD": "日销售离群",
}
STATES = {
    "clear": "未触发",
    "triggered": "已触发",
    "insufficient_data": "数据或样本不足",
    "insufficient_baseline": "历史基线不足",
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


def money(metric, result):
    if metric["value"] is None:
        return "不可用（" + str(metric.get("unavailable_reason") or "数据不足") + "）"
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
    return text + ("（估算）" if metric["quality"] == "estimated" else "")


def chart(result, kind):
    # Coordinates are derived from code-computed metrics; labels retain exact decimal formatting.
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
        for x, label in [
            (40, points[0]["start"] if points else ""),
            (570, points[-1]["start"] if points else ""),
        ]:
            svg.append(f'<text x="{x}" y="240" font-size="12">{escape(str(label))}</text>')
        svg.append('<text x="40" y="24" font-size="14">净销售额趋势（覆盖不完整处断开）</text>')
    else:
        data = result["contributions"]
        rows = (data.get("gainers", [])[:3] + data.get("decliners", [])[:3])[:6]
        if not data.get("available") or not rows:
            svg.append('<text x="40" y="90">本期无可比较的销售贡献数据</text>')
        else:
            maximum = max(abs(Decimal(r["sales_contribution_minor"])) for r in rows) or Decimal(1)
            for i, row in enumerate(rows):
                delta = Decimal(row["sales_contribution_minor"])
                y = 25 + i * 36
                svg.append(
                    f'<text x="14" y="{y + 14}" font-size="11">'
                    f"{escape(str(row.get('sku') or '未映射')[:18])}</text>"
                )
                width = float(abs(delta) / maximum) * 370
                svg.append(
                    f'<rect x="170" y="{y}" width="{width:.2f}" height="19" '
                    f'fill="{"#92ac78" if delta >= 0 else "#bc917e"}"/>'
                )
                label = money(
                    {"value": str(delta), "unit": "minor_currency", "quality": "confirmed"}, result
                )
                svg.append(f'<text x="550" y="{y + 14}" font-size="11">{escape(label)}</text>')
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


def document(content, evidence):
    result = content["metrics"]
    parts = [
        f"<h1>{escape(content['title'])}</h1>",
        '<p class="meta">ShopPulse · 冻结经营报告 · 修订 '
        + str(content["revision"])
        + "<br>报告 ID "
        + escape(content["report_id"])
        + "<br>"
        + escape(result["query"]["start"])
        + " ≤ 支付日期 &lt; "
        + escape(result["query"]["end_exclusive"])
        + "<br>时区 "
        + escape(result["timezone"])
        + " · 币种 "
        + escape(result["currency"])
        + "<br>模式 "
        + escape(content["generation_mode"])
        + " · 引擎 "
        + escape(result["engine_version"])
        + "<br>数据版本 "
        + escape(result["dataset_id"])
        + " · 截止 "
        + escape(result["source_as_of"])
        + "</p>",
    ]
    if content.get("model_error_code") not in (None, "NO_MODEL"):
        parts.append('<p class="notice">模型分析未通过或不可用，保留确定性摘要。</p>')
    parts.append("<h2>经营概览</h2>")
    for line in content["summary"]:
        parts.append(
            '<p class="fact">'
            + escape(line["text"])
            + '<br><span class="evidence">证据 '
            + escape(", ".join(line["evidence_refs"]))
            + "</span></p>"
        )
    parts.append("<table><thead><tr><th>指标</th><th>本期</th><th>比较期</th></tr></thead><tbody>")
    for item in content["metric_cards"]:
        previous = result["previous"]
        parts.append(
            "<tr><td>"
            + escape(item["label"])
            + "</td><td>"
            + escape(money(item["metric"], result))
            + "</td><td>"
            + escape(money(previous["metrics"][item["key"]], result) if previous else "未选择")
            + "</td></tr>"
        )
    parts.append("</tbody></table><h2>趋势与销售贡献</h2>")
    for kind in ("trend", "contributions"):
        parts.append('<div class="chart">' + chart(result, kind) + "</div>")
    parts.append(
        "<h2>商品表现（净销售额前十项）</h2><table><thead><tr>"
        "<th>SKU / 商品</th><th>净销售额</th><th>商"
        "品毛利</th><th>支付件数</th></tr></thead><tbody>"
    )
    for row in content["products"]:
        parts.append(
            "<tr><td>"
            + escape(str(row["sku"] or "未映射"))
            + "<br>"
            + escape(row["product_name"])
            + "</td>"
            + "".join(
                "<td>" + escape(money(row["current"]["metrics"][key], result)) + "</td>"
                for key in ("net_sales", "gross_profit", "paid_units")
            )
            + "</tr>"
        )
    parts.append("</tbody></table><h2>异常与限制</h2>")
    for item in content["anomalies"]["checks"]:
        parts.append(
            "<h3>"
            + RULES[item["code"]]
            + "："
            + STATES[item["state"]]
            + "</h3><p>"
            + escape(item["limitation"])
            + '</p><p class="evidence">实际值与阈值：'
            + escape(json.dumps(item["values"], ensure_ascii=False))
            + "</p>"
        )
    parts.append(
        '<p class="notice">质量标记：' + escape(", ".join(content["warnings"]) or "无") + "</p><ul>"
    )
    parts.extend("<li>" + escape(item) + "</li>" for item in content["limitations"])
    parts.append("</ul><h2>经营观察与行动建议</h2>")
    for finding in content["findings"]:
        parts.append(
            "<h3>"
            + escape(finding["title"])
            + "</h3><p>"
            + escape(finding["observation"]["text"])
            + "</p>"
        )
        parts.extend("<p>待验证假设：" + escape(s) + "</p>" for s in finding["hypotheses"])
        parts.append(
            '<p class="evidence">证据 ' + escape(", ".join(finding["evidence_refs"])) + "</p>"
        )
    for item in content["recommendations"]:
        parts.append(
            '<p class="fact">'
            + escape(item["action"])
            + "<br>优先级 "
            + escape(item["priority"])
            + " · 工作量 "
            + escape(item["effort"])
            + " · 验证指标 "
            + escape(item["verification_metric"])
            + " · 复查 "
            + escape(item["suggested_review_window"])
            + "</p>"
        )
    parts.append(
        "<h2>证据附录</h2><p>证据绑定本报告范围。完整工具结果保存在应用中；"
        "HTML 中可展开查看，Markdown 包另含 evidence.json。</p>"
    )
    for ev in evidence:
        parts.append(
            '<p class="evidence"><b>'
            + escape(ev["tool"])
            + "</b><br>ID "
            + escape(ev["evidence_id"])
            + "<br>SHA-256 "
            + escape(ev["result_hash"])
            + "<br>范围 "
            + escape(json.dumps(ev["scope"], ensure_ascii=False))
            + "</p>"
        )
    parts.append(
        "<details><summary>完整计算证据</summary><pre>"
        + escape(json.dumps(evidence, ensure_ascii=False, indent=2))
        + "</pre></details>"
    )
    return "".join(parts)


def html_document(content, evidence):
    body = document(content, evidence)
    # Only a server-authored template, escaped data and data-embedded font; no scripts or URLs.
    text = re.sub("<[^>]+>", "", body)
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="C'
        "ontent-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inli"
        "ne'; font-src data:; img-src data:; base-uri 'none'; form-action 'none'\"><t"
        "itle>ShopPulse 报告</title><style>"
        + CSS
        + font_css(text)
        + "</style><body>"
        + body
        + "</body></html>"
    )


def markdown_zip(content, evidence):
    result = content["metrics"]

    def safe(value):
        return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", escape(str(value))).replace("\n", " ")

    lines = [
        "# " + safe(content["title"]),
        "",
        "报告 " + content["report_id"] + " · 修订 " + str(content["revision"]),
        "",
        safe(json.dumps(result["query"], ensure_ascii=False)),
        "",
        "模式 " + safe(content["generation_mode"]),
        "",
        "币种 " + result["currency"] + " · 时区 " + result["timezone"],
        "",
        "## 经营概览",
        "",
    ]
    for s in content["summary"]:
        lines += [safe(s["text"]), "", "证据：" + ", ".join(s["evidence_refs"]), ""]
    lines += ["| 指标 | 本期 | 比较期 |", "| --- | --- | --- |"]
    for c in content["metric_cards"]:
        previous = (
            money(result["previous"]["metrics"][c["key"]], result)
            if result["previous"]
            else "未选择"
        )
        lines.append(
            "| "
            + safe(c["label"])
            + " | "
            + safe(money(c["metric"], result))
            + " | "
            + safe(previous)
            + " |"
        )
    lines += [
        "",
        "## 图表",
        "",
        "![净销售趋势](trend.svg)",
        "",
        "![销售贡献](contributions.svg)",
        "",
        "## 商品表现",
        "",
        "| SKU / 商品 | 净销售额 | 毛利 | 件数 |",
        "| --- | --- | --- | --- |",
    ]
    for row in content["products"]:
        lines.append(
            "| "
            + safe(str(row["sku"] or "未映射") + " / " + row["product_name"])
            + " | "
            + " | ".join(
                safe(money(row["current"]["metrics"][k], result))
                for k in ("net_sales", "gross_profit", "paid_units")
            )
            + " |"
        )
    lines += ["", "## 异常与限制", ""]
    for c in content["anomalies"]["checks"]:
        lines += [
            "### " + RULES[c["code"]] + "：" + STATES[c["state"]],
            "",
            safe(c["limitation"]),
            "",
            safe(json.dumps(c["values"], ensure_ascii=False)),
            "",
        ]
    lines += [safe(s) for s in content["limitations"]] + [
        "",
        "质量标记：" + safe(", ".join(content["warnings"])),
        "",
        "## 建议",
        "",
    ]
    for f in content["findings"]:
        lines += [
            safe(f["observation"]["text"]),
            "",
            *["待验证假设：" + safe(h) for h in f["hypotheses"]],
            "",
        ]
    for a in content["recommendations"]:
        lines += [
            safe(a["action"]),
            "",
            safe(json.dumps({k: v for k, v in a.items() if k != "action"}, ensure_ascii=False)),
            "",
        ]
    lines += ["## 证据附录", "", "完整证据见同包 evidence.json。", ""]
    for ev in evidence:
        lines += [safe(ev["tool"]) + ": " + ev["evidence_id"] + " / " + ev["result_hash"], ""]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.md", "\n".join(lines))
        archive.writestr("evidence.json", json.dumps(evidence, ensure_ascii=False, indent=2))
        for kind in ("trend", "contributions"):
            archive.writestr(kind + ".svg", chart(result, kind))
    return output.getvalue()
