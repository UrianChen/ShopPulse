"""Synthetic-only development provider. Never logs requests or credentials."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384 or self.path != "/v1/chat/completions":
                self.send_error(400)
                return
            data = json.loads(self.rfile.read(size))
            model = data.get("model")
            status, body = 200, completion()
            if model in {"auth-fail", "missing", "rate-limit", "unavailable"}:
                status = {"auth-fail": 401, "missing": 404, "rate-limit": 429, "unavailable": 503}[
                    model
                ]
                body = {"error": {"message": "Synthetic provider error. Never display this body."}}
            elif model == "redirect":
                status, body = 302, {}
            elif model == "invalid":
                body = {"unexpected": True}
            elif data.get("messages") and "ShopPulse report protocol" in data["messages"][0].get(
                "content", ""
            ):
                body = report_completion(data)
            elif data.get("tools"):
                if model in {"no-tools", "text-json", "narrative"}:
                    status, body = 400, {"error": {"code": "unsupported_parameter"}}
                elif data.get("tool_choice") == "none":
                    body = completion("Synthetic tool result received.")
                else:
                    body = completion(
                        None,
                        [
                            {
                                "id": "call_probe",
                                "type": "function",
                                "function": {
                                    "name": "echo_probe",
                                    "arguments": '{"token":"pulse-test"}',
                                },
                            }
                        ],
                    )
            elif data.get("response_format"):
                if model in {"text-json", "narrative"}:
                    status, body = 400, {"error": {"code": "unsupported_parameter"}}
                else:
                    body = completion('{"ok":true}')
            elif "JSON" in data["messages"][-1]["content"]:
                body = completion("Not structured." if model == "narrative" else '{"ok":true}')
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


def report_completion(data):
    model = data["model"]
    messages = data["messages"]
    repair = any("Repair the schema" in (m.get("content") or "") for m in messages)
    if model == "malformed-report":
        return completion("not JSON")
    if data.get("tools"):
        name = "execute_sql" if model == "unsafe-tool" else "rank_products"
        return completion(
            None,
            [
                {
                    "id": "call_report",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": '{"metric":"gross_profit","direction":"asc","top_k":3}',
                    },
                }
            ],
        )
    if model in {"no-tools", "text-json"} and len(messages) == 2:
        return completion('{"tool":"rank_products","arguments":{"top_k":3}}')
    context = json.loads(messages[1]["content"])
    fact = context["allowed_facts"][0]
    if model == "foreign-evidence":
        fact["bindings"]["value"]["evidence_id"] = "00000000-0000-0000-0000-000000000000"
    if model == "bad-number" or (model == "repair-once" and not repair):
        fact["text_template"] = "销售额是 999999 元。"
    result = {
        "summary": [fact],
        "findings": [
            {
                "id": "f_overview",
                "title": "经营观察",
                "observation": fact,
                "evidence_refs": [fact["bindings"]["value"]["evidence_id"]],
                "hypotheses": ["可能与商品结构和退款分布有关，需核查明细"],
                "limitations": [],
            }
        ],
        "recommendations": [
            {
                "action": "核对退款原因并复查成本记录",
                "rationale_finding_ids": ["f_overview"],
                "priority": "medium",
                "effort": "small",
                "verification_metric": "net_sales",
                "suggested_review_window": "next_week",
            }
        ],
    }
    return completion(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
