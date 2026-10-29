"""Bounded multi-step agent loop (plan, call tools, observe, answer), isolated from the database.

Invariants kept from v1 and enforced here and again by the parent process:
- values, entities and dates reach prose only through evidence bindings (``evidence.py``);
- every tool call yields an evidence record with argument and result hashes;
- requests, tools, rounds, bytes, tokens and wall-clock time are budgeted.
"""

import json
import time

from app.observability.tracing import annotate, span
from app.providers.egress import ProviderError, post
from app.providers.protocols import build, parse, text_of
from app.reports.evidence import validate_analysis, validate_answer
from app.reports.grammar import EvidenceError
from app.reports.prompts import system_prompt
from app.reports.schema import BUDGETS, PROMPT_VERSION, output_schema
from app.reports.tools import (
    CORE,
    DESCRIPTIONS,
    TOOLS,
    ToolError,
    ToolRegistry,
    compact_message,
    digest,
    project,
    tool_message,
    topic_facts,
    wire,
)

__all__ = ["ReportWorkflow", "wire"]

GOALS = {
    "business_review": ["sales_change", "refunds", "margin_and_cost", "product_drivers"],
    "refund_review": ["refunds", "refund_drivers"],
    "profit_review": ["margin_and_cost", "cost_coverage"],
    "product_review": ["product_drivers"],
    "out_of_scope": ["scope"],
}
MISSING_DATA = ["advertising", "traffic", "inventory"]
COMPACT_AFTER_BYTES = 64000
DEBUG_BYTES = 8000


def tool_specs():
    return [
        {
            "name": name,
            "description": DESCRIPTIONS[name],
            "parameters": model.model_json_schema(),
        }
        for name, model in TOOLS.items()
    ]


def tool_catalog():
    return [
        {
            "tool": name,
            "description": DESCRIPTIONS[name],
            "arguments": model.model_json_schema().get("properties", {}),
        }
        for name, model in TOOLS.items()
    ]


class ReportWorkflow:
    def __init__(self, request, transport=post, tools=None, emit=None, drill=None):
        self.request, self.transport = request, transport
        self.config = request["config"]
        self.protocol = self.config.get("protocol") or "openai_chat"
        self.kind = request.get("kind", "report")
        self.language = request.get("language", "zh")
        self.include_names = self.config.get("product_name_mode") == "include_names"
        self.evidence = list(request["evidence"])
        self.known = {e["evidence_id"] for e in self.evidence}
        self.shown = set()
        self.extra = []
        if tools is None:
            registry = ToolRegistry(
                request.get("context"),
                request["report_id"],
                request["run_id"],
                drill=drill,
                cache={(e["tool"], e["args_hash"]): e for e in self.evidence if "args_hash" in e},
            )
            tools = registry.execute
        self.tools = tools
        self.emit = emit or (lambda event: None)
        self.started = time.monotonic()
        self.deadline = self.started + BUDGETS["seconds"] - 15
        self.usage = {
            "requests": 0,
            "input_bytes": 0,
            "output_bytes": 0,
            "provider_input_tokens": 0,
            "provider_output_tokens": 0,
        }
        self.calls = 0
        self.rounds = 0
        self.steps = []
        self.tool_entries = []
        self.drop_format = False

    # ----------------------------------------------------------------- bookkeeping
    def event(self, phase, **data):
        step = {"phase": phase, "t_ms": int((time.monotonic() - self.started) * 1000), **data}
        self.steps.append(step)
        try:
            self.emit(step)
        except Exception:  # Events are observability only; never fail the run.
            pass
        return step

    def scope(self):
        return self.request.get("scope") or self.evidence[0]["scope"]

    # ----------------------------------------------------------------- model calls
    def call(self, messages, tools=None, tool_choice=None, output=None):
        if self.drop_format:
            output = None
        payload = build(
            self.protocol,
            self.config["model_name"],
            messages,
            tools=tools,
            tool_choice=tool_choice,
            output=output,
            max_tokens=4000,
            token_parameter=self.config.get("token_limit_parameter", "none"),
        )
        for attempt in range(2):
            size = len(json.dumps(payload, ensure_ascii=False).encode())
            if (
                self.usage["requests"] >= BUDGETS["requests"]
                or self.usage["input_bytes"] + size > BUDGETS["input_bytes"]
                or time.monotonic() >= self.deadline
            ):
                raise ProviderError("BUDGET_EXCEEDED")
            self.usage["input_bytes"] += size
            self.usage["requests"] += 1
            began = time.monotonic()
            with span(
                "gen_ai.chat",
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.system": self.protocol,
                    "gen_ai.request.model": self.config["model_name"],
                    "shoppulse.request_bytes": size,
                    "shoppulse.request_index": self.usage["requests"],
                },
            ) as item:
                try:
                    body = self.transport(
                        self.config["base_url"],
                        self.request["key"],
                        payload,
                        min(self.config["timeout_seconds"], self.deadline - time.monotonic()),
                        protocol=self.protocol,
                    )
                    answer = parse(self.protocol, body)
                except ProviderError as error:
                    annotate(item, {"error.type": error.code})
                    self.event(
                        "model",
                        request=self.usage["requests"],
                        latency_ms=int((time.monotonic() - began) * 1000),
                        input_bytes=size,
                        error=error.code,
                    )
                    if attempt == 0 and error.code in {"RATE_LIMITED", "PROVIDER_UNAVAILABLE"}:
                        time.sleep(0.25)
                        continue
                    if (
                        error.code == "UNSUPPORTED_REQUEST"
                        and output is not None
                        and tools
                        and not self.drop_format
                    ):
                        # Some services support tools and structured output separately only.
                        self.drop_format = True
                        return self.call(messages, tools, tool_choice, None)
                    raise
                output_bytes = len(json.dumps(answer["visible"], ensure_ascii=False).encode())
                self.usage["output_bytes"] += output_bytes
                self.usage["provider_input_tokens"] += answer["usage"]["input_tokens"]
                self.usage["provider_output_tokens"] += answer["usage"]["output_tokens"]
                annotate(
                    item,
                    {
                        "gen_ai.usage.input_tokens": answer["usage"]["input_tokens"],
                        "gen_ai.usage.output_tokens": answer["usage"]["output_tokens"],
                        "shoppulse.response_bytes": output_bytes,
                        "shoppulse.tool_calls": len(answer["tool_calls"]),
                    },
                )
            debug = (
                {
                    "debug": {
                        "request": json.dumps(payload, ensure_ascii=False)[:DEBUG_BYTES],
                        "response": json.dumps(answer["visible"], ensure_ascii=False)[:DEBUG_BYTES],
                    }
                }
                if self.request.get("debug_capture")
                else {}
            )
            self.event(
                "model",
                request=self.usage["requests"],
                latency_ms=int((time.monotonic() - began) * 1000),
                input_bytes=size,
                output_bytes=output_bytes,
                input_tokens=answer["usage"]["input_tokens"],
                output_tokens=answer["usage"]["output_tokens"],
                tool_calls=[c["name"] for c in answer["tool_calls"]],
                **debug,
            )
            if (
                self.usage["output_bytes"] > BUDGETS["output_bytes"]
                or self.usage["provider_input_tokens"] > BUDGETS["input_tokens"]
                or self.usage["provider_output_tokens"] > BUDGETS["output_tokens"]
            ):
                raise ProviderError("BUDGET_EXCEEDED")
            return answer

    def near_budget(self):
        return (
            self.usage["requests"] >= BUDGETS["requests"] - 2
            or self.usage["input_bytes"] > BUDGETS["input_bytes"] * 0.7
            or time.monotonic() > self.deadline - 60
            or self.calls >= BUDGETS["tools"]
        )

    # ----------------------------------------------------------------- tools
    def run_tools(self, calls):
        results = []
        for index, call in enumerate(calls):
            began = time.monotonic()
            name = call["name"]
            evidence, code = None, None
            args = call["arguments"]
            if index >= BUDGETS["parallel_tools"]:
                code = "TOO_MANY_PARALLEL_CALLS"
            elif args is None:
                code = "INVALID_ARGUMENTS"
            elif name not in TOOLS:
                code = "TOOL_NOT_ALLOWED"
            elif self.calls >= BUDGETS["tools"]:
                code = "TOOL_BUDGET"
            else:
                self.calls += 1
                try:
                    with span("tool." + name, {"shoppulse.tool": name}):
                        evidence = self.tools(name, args)
                except ToolError as error:
                    code = error.code
                except Exception:
                    code = "TOOL_FAILED"
            if evidence is not None and evidence["evidence_id"] in self.shown:
                code = "DUPLICATE_CALL"  # Already in this conversation; the id stays valid.
            elif evidence is not None:
                self.shown.add(evidence["evidence_id"])
                if evidence["evidence_id"] not in self.known:
                    self.known.add(evidence["evidence_id"])
                    self.evidence.append(evidence)
                    self.extra.append(evidence)
            if code:
                content = json.dumps(
                    {
                        "error": code,
                        **({"evidence_id": evidence["evidence_id"]} if evidence else {}),
                    }
                )
            else:
                content = tool_message(evidence, self.include_names)
            self.event(
                "tool",
                tool=name if isinstance(name, str) else "?",
                args_hash=digest(args) if isinstance(args, dict) else None,
                ok=code is None,
                code=code,
                evidence_id=evidence["evidence_id"] if evidence and not code else None,
                latency_ms=int((time.monotonic() - began) * 1000),
            )
            results.append((call, code, content, None if code else evidence))
        return results

    def compact(self, messages):
        if self.protocol == "anthropic_messages":
            return  # Append-only history: compaction would invalidate replayed thinking blocks.
        if len(json.dumps(messages, ensure_ascii=False).encode()) <= COMPACT_AFTER_BYTES:
            return
        count = 0
        for round_index, message, evidence in self.tool_entries:
            if round_index < self.rounds and evidence is not None and not message.get("compacted"):
                message["content"] = compact_message(evidence)
                message["compacted"] = True
                count += 1
        if count:
            self.event("compact", messages=count)

    # ----------------------------------------------------------------- prompts
    def initial_messages(self, strategy, facts):
        initial = []
        for cap in (5, 3, 1):
            initial = [
                {
                    "evidence_id": e["evidence_id"],
                    "tool": e["tool"],
                    "args": e.get("args", {}),
                    "data": project(e["payload"], self.include_names, cap),
                }
                for e in self.evidence
                if e["tool"] in CORE
                and e["tool"] != "get_sales_trend"
                or e["tool"] in {"check_recommendation", "get_merchant_notes"}
            ]
            if len(json.dumps(initial, ensure_ascii=False).encode()) <= 24000:
                break
        self.shown = {item["evidence_id"] for item in initial}
        data = {
            "kind": self.kind,
            "task": self.request.get("intent", "business_review"),
            "language": self.language,
            "scope": self.scope(),
            "analysis_goals": GOALS.get(self.request.get("intent"), GOALS["business_review"]),
            "fact_examples": facts[:8],
            "evidence": initial,
            "missing_data": MISSING_DATA,
        }
        if strategy == "restricted_json":
            data["tool_catalog"] = tool_catalog()
        if self.kind == "question":
            if self.request.get("question") is not None:
                data["question"] = self.request["question"]
            if self.request.get("conversation"):
                data["conversation"] = self.request["conversation"]
        system = system_prompt(
            self.request.get("prompt_version", PROMPT_VERSION),
            self.kind,
            self.language,
            strategy,
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ]

    def output_for(self, strategy, final):
        caps = self.config["capabilities"]
        schema = {
            "type": "json_schema",
            "name": "shoppulse_" + self.kind,
            "schema": output_schema(self.kind),
        }
        if strategy == "restricted_json" and not final:
            return {"type": "json_object"} if caps.get("native_json") else None
        if caps.get("json_schema"):
            return schema
        return {"type": "json_object"} if caps.get("native_json") else None

    def envelope_calls(self, answer):
        try:
            parsed = json.loads(text_of(answer))
        except (ValueError, ProviderError):
            return []
        if not isinstance(parsed, dict):
            return []
        if set(parsed) == {"tool", "arguments"}:
            items = [parsed]
        elif set(parsed) == {"tools"} and isinstance(parsed["tools"], list):
            items = parsed["tools"]
        else:
            return []
        calls = []
        for i, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get("tool"), str):
                return []
            arguments = item.get("arguments", {})
            calls.append(
                {
                    "id": f"json_{self.rounds}_{i}",
                    "name": item["tool"][:64],
                    "arguments": arguments if isinstance(arguments, dict) else None,
                }
            )
        return calls

    def validate(self, raw):
        validator = validate_analysis if self.kind == "report" else validate_answer
        return validator(
            raw,
            self.evidence,
            self.request["report_id"],
            self.request["dataset_id"],
            self.request["currency"],
            self.request["currency_exponent"],
            self.scope(),
            self.language,
            self.include_names,
        )

    def repair_message(self, issues):
        lines = [
            f"- {i['at']}: {i['code']}" + (f" ({i['hint']})" if i.get("hint") else "")
            for i in issues
        ]
        return (
            "Your last reply failed validation and was not shown to the merchant. Fix these "
            "problems and reply with the complete final JSON only. Keep values in bindings; tools "
            "are closed.\n" + "\n".join(lines)
        )

    # ----------------------------------------------------------------- loop
    def run(self):
        error, analysis, raw_final, repairs = None, None, None, 0
        with span(
            "agent.workflow",
            {"shoppulse.kind": self.kind, "shoppulse.protocol": self.protocol},
            self.request.get("traceparent"),
        ) as root:
            try:
                facts = topic_facts(
                    self.evidence, self.request.get("intent", "business_review"), self.language
                )
                if not facts:
                    raise ProviderError("INSUFFICIENT_EVIDENCE")
                strategy = self.config["capabilities"]["strategy"]
                native = strategy == "native_tools"
                envelope = strategy == "restricted_json"
                specs = tool_specs() if native else None
                messages = self.initial_messages(strategy, facts)
                forced = not (native or envelope)
                self.event(
                    "plan", strategy=strategy, goals=len(GOALS.get(self.request.get("intent"), []))
                )
                while True:
                    answer = self.call(
                        messages,
                        tools=specs,
                        tool_choice="none" if native and forced else None,
                        output=self.output_for(strategy, forced),
                    )
                    calls = answer["tool_calls"] if native else []
                    if envelope and not forced:
                        calls = self.envelope_calls(answer)
                    if calls and forced:
                        # Tools are closed: answer every call with an error and ask for the result.
                        if repairs >= BUDGETS["repairs"]:
                            raise ProviderError("EVIDENCE_VALIDATION_FAILED")
                        repairs += 1
                        messages.append(self.assistant_entry(answer))
                        messages += self.closed_results(calls, native)
                        messages.append(
                            {
                                "role": "user",
                                "content": self.repair_message(
                                    [{"at": "$", "code": "TOOLS_CLOSED"}]
                                ),
                            }
                        )
                        self.event("repair", codes=["TOOLS_CLOSED"])
                        continue
                    if calls:
                        self.rounds += 1
                        messages.append(self.assistant_entry(answer, calls if envelope else None))
                        results = self.run_tools(calls)
                        new = any(code is None for _, code, _, _ in results)
                        if native:
                            for call, code, content, evidence in results:
                                entry = {
                                    "role": "tool",
                                    "tool_call_id": call["id"],
                                    "name": call["name"],
                                    "content": content,
                                    "is_error": code is not None,
                                }
                                messages.append(entry)
                                self.tool_entries.append((self.rounds, entry, evidence))
                        else:
                            entry = {
                                "role": "user",
                                "content": "Tool results DATA: "
                                + json.dumps(
                                    [json.loads(c) for _, _, c, _ in results], ensure_ascii=False
                                ),
                            }
                            messages.append(entry)
                        reason = (
                            "no_new_evidence"
                            if not new
                            else "round_limit"
                            if self.rounds >= BUDGETS["tool_rounds"]
                            else "budget"
                            if self.near_budget()
                            else None
                        )
                        if reason:
                            forced = True
                            self.event("finalize", reason=reason)
                            messages.append(
                                {
                                    "role": "user",
                                    "content": "Tools are now closed. Reply with the final JSON.",
                                }
                            )
                        self.compact(messages)
                        continue
                    try:
                        text = text_of(answer)
                        raw_final = json.loads(text)
                        analysis = self.validate(raw_final)
                        self.event("validated", repairs=repairs)
                        break
                    except (ValueError, TypeError, KeyError, RecursionError, ProviderError) as exc:
                        issues = (
                            exc.issues
                            if isinstance(exc, EvidenceError)
                            else [
                                {
                                    "at": "$",
                                    "code": "INVALID_JSON",
                                    "hint": "reply with one JSON object",
                                }
                            ]
                        )
                        if repairs >= BUDGETS["repairs"]:
                            raise ProviderError("EVIDENCE_VALIDATION_FAILED") from None
                        repairs += 1
                        forced = True
                        self.event("repair", codes=[i["code"] for i in issues][:8])
                        if answer.get("content") or answer.get("raw"):
                            messages.append(self.assistant_entry(answer))
                        messages.append({"role": "user", "content": self.repair_message(issues)})
            except ProviderError as exc:
                error = exc.code
            except Exception:
                error = "MODEL_OUTPUT_INVALID"
            annotate(
                root,
                {
                    "shoppulse.requests": self.usage["requests"],
                    "shoppulse.tools": self.calls,
                    "shoppulse.repairs": repairs,
                    **({"error.type": error} if error else {}),
                },
            )
        self.event("completed", error=error, repairs=repairs)
        return {
            "analysis": analysis,
            "raw_analysis": raw_final if analysis else None,
            "error_code": error,
            "repaired": repairs > 0,
            "repairs": repairs,
            "usage": {**self.usage, "tools": self.calls, "tool_rounds": self.rounds},
            "steps": self.steps,
            "extra_evidence": self.extra,
        }

    def assistant_entry(self, answer, envelope_calls=None):
        if envelope_calls is not None:
            return {"role": "assistant", "content": answer.get("content")}
        return {
            "role": "assistant",
            "content": answer.get("content"),
            "tool_calls": [
                {"id": c["id"], "name": c["name"], "arguments": c["arguments"] or {}}
                for c in answer["tool_calls"]
            ],
            "raw": answer.get("raw"),
        }

    def closed_results(self, calls, native):
        if not native:
            return [{"role": "user", "content": json.dumps({"error": "TOOLS_CLOSED"})}]
        return [
            {
                "role": "tool",
                "tool_call_id": c["id"],
                "name": c["name"],
                "content": json.dumps({"error": "TOOLS_CLOSED"}),
                "is_error": True,
            }
            for c in calls
        ]
