"""Synthetic-only development provider. Never logs requests or credentials.

Speaks OpenAI Chat Completions (/v1/chat/completions), OpenAI Responses (/v1/responses) and
Anthropic Messages (/v1/messages). The model name selects a scripted behaviour, so tests, the
Compose end-to-end suite and offline evaluations exercise the real protocol and agent loop.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTES = {
    "/v1/chat/completions": "openai_chat",
    "/v1/responses": "openai_responses",
    "/v1/messages": "anthropic_messages",
}
NO_TOOLS = {"no-tools", "text-json", "narrative"}
NO_JSON_MODE = {"text-json", "narrative"}
NO_SCHEMA = {"text-json", "narrative", "no-tools"}


class Unsupported(Exception):
    pass


def completion(content="OK", calls=None):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls" if calls else "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                    **({"tool_calls": calls} if calls else {}),
                },
            }
        ]
    }


# --------------------------------------------------------------------------- wire conversion
def to_neutral(protocol, payload):
    """Return (messages, request) with request flags {tools, tool_choice_none, json, schema}."""
    messages = []
    if protocol == "openai_chat":
        for m in payload.get("messages") or []:
            if m.get("role") == "assistant":
                messages.append(
                    {
                        "role": "assistant",
                        "content": m.get("content"),
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "name": c["function"]["name"],
                                "arguments": json.loads(c["function"]["arguments"] or "{}"),
                            }
                            for c in m.get("tool_calls") or []
                        ],
                    }
                )
            elif m.get("role") == "tool":
                messages.append(
                    {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]}
                )
            else:
                messages.append({"role": m.get("role"), "content": m.get("content") or ""})
        response_format = (payload.get("response_format") or {}).get("type")
        flags = {
            "tools": bool(payload.get("tools")),
            "tool_choice_none": payload.get("tool_choice") == "none",
            "json": response_format == "json_object",
            "schema": response_format == "json_schema",
        }
    elif protocol == "openai_responses":
        if payload.get("instructions"):
            messages.append({"role": "system", "content": payload["instructions"]})
        for item in payload.get("input") or []:
            kind = item.get("type")
            if kind == "function_call":
                call = {
                    "id": item["call_id"],
                    "name": item["name"],
                    "arguments": json.loads(item.get("arguments") or "{}"),
                }
                if messages and messages[-1]["role"] == "assistant" and messages[-1].get("open"):
                    messages[-1]["tool_calls"].append(call)
                else:
                    messages.append(
                        {"role": "assistant", "content": None, "tool_calls": [call], "open": True}
                    )
            elif kind == "function_call_output":
                messages.append(
                    {"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]}
                )
            elif kind == "message":
                text = "".join(p.get("text", "") for p in item.get("content") or [])
                messages.append({"role": "assistant", "content": text, "tool_calls": []})
            else:
                content = item.get("content")
                if isinstance(content, list):
                    content = "".join(p.get("text", "") for p in content)
                messages.append({"role": item.get("role", "user"), "content": content or ""})
        fmt = ((payload.get("text") or {}).get("format") or {}).get("type")
        flags = {
            "tools": bool(payload.get("tools")),
            "tool_choice_none": payload.get("tool_choice") == "none",
            "json": fmt == "json_object",
            "schema": fmt == "json_schema",
        }
    else:
        if not isinstance(payload.get("max_tokens"), int):
            raise Unsupported
        if payload.get("system"):
            messages.append({"role": "system", "content": payload["system"]})
        for m in payload.get("messages") or []:
            content = m.get("content")
            if m.get("role") == "assistant":
                blocks = (
                    content if isinstance(content, list) else [{"type": "text", "text": content}]
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(
                            b.get("text", "") for b in blocks if b.get("type") == "text"
                        )
                        or None,
                        "tool_calls": [
                            {"id": b["id"], "name": b["name"], "arguments": b.get("input") or {}}
                            for b in blocks
                            if b.get("type") == "tool_use"
                        ],
                    }
                )
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": block["tool_use_id"],
                                "content": block.get("content") or "",
                            }
                        )
                    elif block.get("type") == "text":
                        messages.append({"role": "user", "content": block["text"]})
            else:
                messages.append({"role": "user", "content": content or ""})
        flags = {
            "tools": bool(payload.get("tools")),
            "tool_choice_none": (payload.get("tool_choice") or {}).get("type") == "none",
            "json": False,
            "schema": ((payload.get("output_config") or {}).get("format") or {}).get("type")
            == "json_schema",
        }
    return messages, flags


def from_neutral(protocol, content, calls, usage=(120, 40)):
    if protocol == "openai_chat":
        body = completion(
            content,
            [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
                }
                for c in calls
            ]
            or None,
        )
        body["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1]}
        return body
    if protocol == "openai_responses":
        output = []
        if content is not None:
            output.append(
                {
                    "type": "message",
                    "id": "msg_mock",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content}],
                }
            )
        output += [
            {
                "type": "function_call",
                "id": "fc_" + c["id"],
                "call_id": c["id"],
                "name": c["name"],
                "arguments": json.dumps(c["arguments"]),
            }
            for c in calls
        ]
        return {
            "id": "resp_mock",
            "status": "completed",
            "output": output,
            "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
        }
    blocks = [{"type": "thinking", "thinking": "", "signature": "mock-signature"}]
    if content is not None:
        blocks.append({"type": "text", "text": content})
    blocks += [
        {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
        for c in calls
    ]
    return {
        "id": "msg_mock",
        "type": "message",
        "role": "assistant",
        "content": blocks,
        "stop_reason": "tool_use" if calls else "end_turn",
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }


# --------------------------------------------------------------------------- scripted agent
def tool_results(messages):
    found = []
    for m in messages:
        if m["role"] == "tool":
            try:
                found.append(json.loads(m["content"]))
            except (TypeError, ValueError):
                pass
        elif m["role"] == "user" and str(m.get("content", "")).startswith("Tool results DATA: "):
            found += json.loads(m["content"][len("Tool results DATA: ") :])
    return found


def sentence(template, *bindings):
    return {
        "template": template,
        "bindings": [
            {"name": name, "evidence_id": evidence_id, "path": path, "format": fmt}
            for name, evidence_id, path, fmt in bindings
        ],
    }


def entity_sentences(results, language):
    """Bind a SKU from the richest drill-down result available."""
    for result in reversed(results):
        data = result.get("data") or {}
        if result.get("tool") == "inspect_sku" and data.get("sku"):
            ev = result["evidence_id"]
            if language == "en":
                return sentence(
                    "Refunds on {{sku}} reached {{refund}}.",
                    ("sku", ev, "sku", "entity"),
                    ("refund", ev, "current.metrics.refund_amount", "money"),
                ), ev
            return sentence(
                "商品 {{sku}} 的累计退款为 {{refund}}。",
                ("sku", ev, "sku", "entity"),
                ("refund", ev, "current.metrics.refund_amount", "money"),
            ), ev
        items = data.get("items") or []
        if (
            result.get("tool") in {"rank_products", "refund_breakdown"}
            and items
            and items[0].get("sku")
        ):
            ev = result["evidence_id"]
            prefix = (
                "items.0.current.metrics"
                if result["tool"] == "rank_products"
                else "items.0.metrics"
            )
            if language == "en":
                return sentence(
                    "{{sku}} is the first product in this ranking with net sales of {{sales}}.",
                    ("sku", ev, "items.0.sku", "entity"),
                    ("sales", ev, prefix + ".net_sales", "money"),
                ), ev
            return sentence(
                "排名首位的商品是 {{sku}}，净销售额为 {{sales}}。",
                ("sku", ev, "items.0.sku", "entity"),
                ("sales", ev, prefix + ".net_sales", "money"),
            ), ev
    return None, None


def final_report(model, data, results, repaired):
    language = data.get("language", "zh")
    fact = data["fact_examples"][0]
    if model == "foreign-evidence":
        fact["bindings"][0]["evidence_id"] = "00000000-0000-0000-0000-000000000000"
    if model == "bad-number" or (model == "repair-once" and not repaired):
        fact["template"] = "销售额是 999999 元。"
    support, _ = entity_sentences(results, language)
    hypothesis = (
        "May relate to product mix and refund distribution; check the details."
        if language == "en"
        else "可能与商品结构和退款分布有关，需核查明细"
    )
    if support:
        template = (
            "Review refund reasons and cost records for {{sku}}."
            if language == "en"
            else "核对 {{sku}} 的退款原因并复查成本记录"
        )
        action = {"template": template, "bindings": [dict(support["bindings"][0])]}
    else:
        action = sentence(
            "Review refund reasons and cost records."
            if language == "en"
            else "核对退款原因并复查成本记录"
        )
    return {
        "summary": [fact],
        "findings": [
            {
                "id": "f_overview",
                "topic": "sales",
                "title": "Business overview" if language == "en" else "经营观察",
                "observation": fact,
                "supporting": [support] if support else [],
                "hypotheses": [sentence(hypothesis)],
            }
        ],
        "recommendations": [
            {
                "action": action,
                "rationale_finding_ids": ["f_overview"],
                "priority": "medium",
                "effort": "small",
                "verification_metric": "net_sales",
                "suggested_review_window": "next_week",
            }
        ],
    }


def final_answer(model, data, results):
    language = data.get("language", "zh")
    if model == "clarify":
        return {
            "kind": "clarify",
            "answer": [],
            "findings": [],
            "recommendations": [],
            "clarify": sentence(
                "Do you mean refunds or margin?" if language == "en" else "你想了解退款还是毛利？"
            ),
            "options": ["Refunds", "Margin"] if language == "en" else ["退款", "毛利"],
            "suggested_query": None,
        }
    if model == "suggest":
        scope = data["scope"]
        return {
            "kind": "suggested_query",
            "answer": [],
            "findings": [],
            "recommendations": [],
            "clarify": sentence(
                "This needs the previous period as its own report."
                if language == "en"
                else "需要单独分析比较期，请新建报告。"
            ),
            "options": [],
            "suggested_query": {
                "start": scope["compare_start"] or scope["start"],
                "end_exclusive": scope["compare_end_exclusive"] or scope["end_exclusive"],
                "comparison": "previous",
                "skus": [],
            },
        }
    support, _ = entity_sentences(results, language)
    return {
        "kind": "answer",
        "answer": [data["fact_examples"][0]] + ([support] if support else []),
        "findings": [],
        "recommendations": [],
        "clarify": None,
        "options": [],
        "suggested_query": None,
    }


def first_id(results, tool):
    for result in results:
        if result.get("tool") == tool and result.get("evidence_id"):
            return result
    return None


def agent_turn(model, messages, flags):
    """Return (content, calls) for a ShopPulse analysis conversation."""
    data = json.loads(messages[1]["content"])
    results = tool_results(messages)
    repaired = any("failed validation" in str(m.get("content") or "") for m in messages)
    rounds = sum(1 for m in messages if m["role"] == "assistant" and m.get("tool_calls"))
    envelope_rounds = sum(
        1
        for m in messages
        if m["role"] == "user" and str(m.get("content")).startswith("Tool results")
    )
    closed = any("Tools are now closed" in str(m.get("content") or "") for m in messages)
    final = (
        final_report(model, data, results, repaired)
        if data["kind"] == "report"
        else final_answer(model, data, results)
    )
    if model == "malformed-report":
        return "not JSON", []
    if flags["tools"] and not flags["tool_choice_none"] and not repaired and not closed:
        if model == "unsafe-tool" and rounds == 0:
            return None, [{"id": "call_sql", "name": "execute_sql", "arguments": {"sql": "DROP"}}]
        if model == "agent":
            if rounds == 0:
                return None, [
                    {"id": "call_refunds", "name": "refund_breakdown", "arguments": {"by": "sku"}},
                    {
                        "id": "call_rank",
                        "name": "rank_products",
                        "arguments": {"metric": "net_sales", "direction": "desc", "top_k": 3},
                    },
                ]
            refunds = first_id(results, "refund_breakdown")
            items = ((refunds or {}).get("data") or {}).get("items") or []
            if rounds == 1 and items:
                return None, [
                    {"id": "call_sku", "name": "inspect_sku", "arguments": {"sku": items[0]["sku"]}}
                ]
            if rounds <= 2:
                # Repeat an identical call: the loop must reject it and close the tool round.
                return None, [
                    {"id": "call_dup", "name": "refund_breakdown", "arguments": {"by": "sku"}}
                ]
        if model in {"full", "clarify", "suggest", "answer"} and rounds == 0:
            if data["kind"] == "report":
                args = {"metric": "gross_profit", "direction": "asc", "top_k": 3}
                return None, [{"id": "call_report", "name": "rank_products", "arguments": args}]
            return None, [{"id": "call_question", "name": "refund_breakdown", "arguments": {}}]
    if model in {"no-tools", "text-json"} and envelope_rounds == 0 and not repaired and not closed:
        return json.dumps({"tools": [{"tool": "rank_products", "arguments": {"top_k": 3}}]}), []
    return json.dumps(final, ensure_ascii=False), []


def probe_turn(model, messages, flags):
    last = str(messages[-1].get("content") or "") if messages else ""
    if flags["tools"]:
        if model in NO_TOOLS:
            raise Unsupported
        if any(m["role"] == "tool" for m in messages):
            return "Synthetic tool result received.", []
        return None, [
            {"id": "call_probe", "name": "echo_probe", "arguments": {"token": "pulse-test"}}
        ]
    if flags["json"]:
        if model in NO_JSON_MODE:
            raise Unsupported
        return '{"ok":true}', []
    if flags["schema"]:
        if model in NO_SCHEMA:
            raise Unsupported
        return '{"ok":true}', []
    if "JSON" in last:
        return ("Not structured." if model == "narrative" else '{"ok":true}'), []
    return "OK", []


def respond(protocol, payload):
    """Return (status, body) for a request in any supported protocol."""
    model = payload.get("model")
    if model in {"auth-fail", "missing", "rate-limit", "unavailable"}:
        status = {"auth-fail": 401, "missing": 404, "rate-limit": 429, "unavailable": 503}[model]
        return status, {"error": {"message": "Synthetic provider error. Never display this body."}}
    if model == "redirect":
        return 302, {}
    if model == "invalid":
        return 200, {"unexpected": True}
    try:
        messages, flags = to_neutral(protocol, payload)
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        if "ShopPulse analysis protocol" in system:
            if flags["tools"] and model in NO_TOOLS:
                raise Unsupported
            content, calls = agent_turn(model, messages, flags)
        else:
            content, calls = probe_turn(model, messages, flags)
    except Unsupported:
        return 400, {"error": {"code": "unsupported_parameter"}}
    return 200, from_neutral(protocol, content, calls)


def report_completion(data, protocol="openai_chat"):
    """In-process helper for tests: respond to a wire payload without HTTP."""
    status, body = respond(protocol, data)
    if status != 200:
        raise ValueError(status)
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            protocol = ROUTES.get(self.path)
            if not 0 < size <= 1024 * 1024 or protocol is None:
                self.send_error(400)
                return
            data = json.loads(self.rfile.read(size))
            if protocol == "anthropic_messages" and not self.headers.get("anthropic-version"):
                status, body = 400, {"error": {"type": "invalid_request_error"}}
            else:
                status, body = respond(protocol, data)
            raw = json.dumps(body).encode()
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (ValueError, KeyError, TypeError, OSError):
            self.close_connection = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
