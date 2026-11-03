"""Bounded agent loop, isolated from the database.

Reports (v3) follow a hypothesis loop: the model plans hypotheses, each with a test (one read-only
tool call) and a machine-checkable expectation; the server runs every test and decides supported,
refuted or inconclusive; one optional deeper wave builds on supported hypotheses; then the model
writes the report. Findings may only cite supported hypotheses and "ruled out" only refuted ones.
Models without native tools or JSON fall back to the v2 tool loop, as do follow-up questions.

Invariants kept from v1 and enforced here and again by the parent process:
- values, entities and dates reach prose only through evidence bindings (``evidence.py``);
- every tool call yields an evidence record with argument and result hashes;
- requests, tools, rounds, bytes, tokens and wall-clock time are budgeted.
"""

import json
import time

from pydantic import ValidationError

from app.observability.tracing import annotate, span
from app.providers.egress import ProviderError, post
from app.providers.protocols import build, parse, text_of
from app.reports import patches
from app.reports.evidence import lint, validate_analysis, validate_answer
from app.reports.grammar import EvidenceError
from app.reports.hypothesis import verdict_summary
from app.reports.prompts import load, system_prompt
from app.reports.schema import PROMPT_VERSION, Plan, Review, budgets_for, output_schema
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
CONTEXT_TOOLS = {"check_recommendation", "get_merchant_notes", "get_history", "recheck_hypotheses"}
HYPOTHESIS_STRATEGIES = {"native_tools", "restricted_json"}
REVIEW_TRIGGERS = {"DIRECTION_MISMATCH", "OVERCLAIM"}


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


def rendered_sentences(analysis):
    """(location, text) of every rendered sentence, using the same locations as the reply."""
    for i, sentence in enumerate(analysis.get("summary") or []):
        yield f"summary[{i}]", sentence["text"]
    for i, finding in enumerate(analysis.get("findings") or []):
        yield f"findings[{i}].observation", finding["observation"]["text"]
        for j, sentence in enumerate(finding["supporting"]):
            yield f"findings[{i}].supporting[{j}]", sentence["text"]
        for j, text in enumerate(finding["hypotheses"]):
            yield f"findings[{i}].hypotheses[{j}]", text
    for i, item in enumerate(analysis.get("recommendations") or []):
        yield f"recommendations[{i}].action", item["action"]
        yield f"recommendations[{i}].verification_metric", item["verification_metric"]
    for i, item in enumerate(analysis.get("ruled_out") or []):
        yield f"ruled_out[{i}].sentence", item["text"]


class ReportWorkflow:
    def __init__(self, request, transport=post, tools=None, emit=None, drill=None):
        self.request, self.transport = request, transport
        self.config = request["config"]
        self.protocol = self.config.get("protocol") or "openai_chat"
        self.kind = request.get("kind", "report")
        self.budgets = budgets_for(self.kind)
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
                evidence=list(self.evidence),
                drill=drill,
                cache={(e["tool"], e["args_hash"]): e for e in self.evidence if "args_hash" in e},
                limit=self.budgets["tools"],
                include_names=self.include_names,
                test_limit=self.budgets["tests"],
            )
            tools = registry.execute
        self.tools = tools
        self.emit = emit or (lambda event: None)
        self.started = time.monotonic()
        self.deadline = self.started + self.budgets["seconds"] - 15
        self.usage = {
            "requests": 0,
            "input_bytes": 0,
            "output_bytes": 0,
            "provider_input_tokens": 0,
            "provider_output_tokens": 0,
        }
        self.calls = 0
        self.tests = 0
        self.rounds = 0
        self.repairs = 0
        self.steps = []
        self.tool_entries = []
        self.drop_format = False
        self.final_answer = None
        self.mode = "tools"

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

    def adopt(self, evidence):
        """Make evidence produced by the server during this run bindable in the reply."""
        if evidence["evidence_id"] not in self.known:
            self.known.add(evidence["evidence_id"])
            self.evidence.append(evidence)
            self.extra.append(evidence)

    # ----------------------------------------------------------------- model calls
    def call(self, messages, tools=None, tool_choice=None, output=None, model=None):
        if self.drop_format:
            output = None
        payload = build(
            self.protocol,
            model or self.config["model_name"],
            messages,
            tools=tools,
            tool_choice=tool_choice,
            output=output,
            max_tokens=4000,
            token_parameter=self.config.get("token_limit_parameter", "none"),
            cache=True,
        )
        for attempt in range(2):
            size = len(json.dumps(payload, ensure_ascii=False).encode())
            if (
                self.usage["requests"] >= self.budgets["requests"]
                or self.usage["input_bytes"] + size > self.budgets["input_bytes"]
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
                    "gen_ai.request.model": model or self.config["model_name"],
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
                        **({"model": model} if model else {}),
                    )
                    if attempt == 0 and error.code in {"RATE_LIMITED", "PROVIDER_UNAVAILABLE"}:
                        time.sleep(0.25)
                        continue
                    if (
                        error.code == "UNSUPPORTED_REQUEST"
                        and output is not None
                        and not self.drop_format
                    ):
                        # Some services refuse tools combined with structured output, or a schema
                        # they consider too large. The reply is still validated in full here.
                        self.drop_format = True
                        return self.call(messages, tools, tool_choice, None, model)
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
                cached_tokens=answer["usage"].get("cached_tokens", 0),
                tool_calls=[c["name"] for c in answer["tool_calls"]],
                **({"model": model} if model else {}),
                **debug,
            )
            if (
                self.usage["output_bytes"] > self.budgets["output_bytes"]
                or self.usage["provider_input_tokens"] > self.budgets["input_tokens"]
                or self.usage["provider_output_tokens"] > self.budgets["output_tokens"]
            ):
                raise ProviderError("BUDGET_EXCEEDED")
            return answer

    def near_budget(self):
        return (
            self.usage["requests"] >= self.budgets["requests"] - 2
            or self.usage["input_bytes"] > self.budgets["input_bytes"] * 0.7
            or time.monotonic() > self.deadline - 60
            or self.calls >= self.budgets["tools"]
        )

    # ----------------------------------------------------------------- tools
    def run_tools(self, calls):
        results = []
        for index, call in enumerate(calls):
            began = time.monotonic()
            name = call["name"]
            evidence, code = None, None
            args = call["arguments"]
            if index >= self.budgets["parallel_tools"]:
                code = "TOO_MANY_PARALLEL_CALLS"
            elif args is None:
                code = "INVALID_ARGUMENTS"
            elif name not in TOOLS:
                code = "TOOL_NOT_ALLOWED"
            elif self.calls >= self.budgets["tools"]:
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
                self.adopt(evidence)
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
    def verdicts(self):
        return [verdict_summary(e) for e in self.evidence if e["tool"] == "test_hypothesis"]

    def initial_messages(self, strategy, facts, phase=None):
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
                or e["tool"] in CONTEXT_TOOLS
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
        hypotheses = self.verdicts()
        if hypotheses:
            data["hypotheses"] = hypotheses
        if phase is not None:
            data["phase"] = phase
            data["hypothesis_budget"] = {
                "per_wave": self.budgets["hypotheses"],
                "waves": self.budgets["waves"],
            }
        if strategy == "restricted_json" or phase is not None:
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

    def structured(self, kind):
        caps = self.config["capabilities"]
        if caps.get("json_schema"):
            return {
                "type": "json_schema",
                "name": "shoppulse_" + kind,
                "schema": output_schema(kind),
            }
        return {"type": "json_object"} if caps.get("native_json") else None

    def output_for(self, strategy, final):
        caps = self.config["capabilities"]
        if strategy == "restricted_json" and not final:
            return {"type": "json_object"} if caps.get("native_json") else None
        return self.structured(self.kind)

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

    # ----------------------------------------------------------------- hypotheses (v3)
    def plan(self, messages, phase):
        """Ask for hypotheses; one repair for malformed plans. Returns specs or None."""
        output = self.structured("plan")
        for attempt in range(2):
            answer = self.call(messages, output=output)
            messages.append(self.assistant_entry(answer))
            try:
                parsed = Plan.model_validate(json.loads(text_of(answer)))
                return parsed.model_dump(mode="json")["hypotheses"]
            except (ValueError, ValidationError, ProviderError, TypeError):
                if attempt:
                    break
                self.event("repair", codes=["INVALID_PLAN"], mode="full", stage=phase)
                messages.append(
                    {
                        "role": "user",
                        "content": "Your hypothesis plan was not valid JSON for the plan format. "
                        'Reply with {"hypotheses": [...]} only.',
                    }
                )
        return None

    def test_wave(self, specs, wave):
        """Server-side tests for one wave. Returns model-facing results."""
        results, states = [], {}
        for spec in specs[: self.budgets["hypotheses"]]:
            began = time.monotonic()
            if self.tests >= self.budgets["tests"]:
                results.append({"id": spec["id"], "error": "TEST_BUDGET"})
                states["error"] = states.get("error", 0) + 1
                continue
            self.tests += 1
            try:
                with span("tool.test_hypothesis", {"shoppulse.tool": spec["test"]["tool"]}):
                    verdict = self.tools("test_hypothesis", {**spec, "wave": wave})
                    test = self.tools(
                        "get_evidence", {"evidence_id": verdict["payload"]["test_evidence_id"]}
                    )
            except ToolError as error:
                results.append({"id": spec["id"], "error": error.code})
                states["error"] = states.get("error", 0) + 1
                self.event("test", id=spec["id"], ok=False, code=error.code)
                continue
            except Exception:
                results.append({"id": spec["id"], "error": "TEST_FAILED"})
                states["error"] = states.get("error", 0) + 1
                continue
            for ev in (test, verdict):
                self.adopt(ev)
            state = verdict["payload"]["state"]
            states[state] = states.get(state, 0) + 1
            entry = {"verdict": verdict_summary(verdict)}
            if test["evidence_id"] not in self.shown:
                self.shown.add(test["evidence_id"])
                entry["test"] = json.loads(tool_message(test, self.include_names, 6000))
            results.append(entry)
            self.event(
                "test",
                id=spec["id"],
                tool=spec["test"]["tool"],
                ok=True,
                state=state,
                reason=verdict["payload"]["reason"],
                evidence_id=verdict["evidence_id"],
                test_evidence_id=test["evidence_id"],
                latency_ms=int((time.monotonic() - began) * 1000),
            )
        self.event("hypotheses", wave=wave, **states)
        return results

    def hypothesis_flow(self, strategy, facts):
        """Plan, test and optionally deepen. Returns messages ready for the final reply."""
        self.mode = "hypotheses"
        messages = self.initial_messages(strategy, facts, "plan")
        self.event("plan", strategy=strategy, mode="hypotheses", seeded=len(self.verdicts()))
        specs = self.plan(messages, "plan")
        if specs is None:
            return None
        results = self.test_wave(specs, 1)
        deeper = (
            self.budgets["waves"] >= 2
            and any(v["state"] == "supported" for v in self.verdicts())
            and self.tests < self.budgets["tests"]
            and not self.near_budget()
        )
        phase = "refine" if deeper else "write"
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "phase": phase,
                        "results": results,
                        "instruction": "Optionally propose up to three deeper hypotheses that "
                        'build on supported ones, as {"hypotheses": [...]}; reply '
                        '{"hypotheses": []} to go straight to writing.'
                        if deeper
                        else "Write the final report JSON now.",
                    },
                    ensure_ascii=False,
                ),
            }
        )
        if deeper:
            more = self.plan(messages, "refine") or []
            content = {"phase": "write", "instruction": "Write the final report JSON now."}
            if more:
                content["results"] = self.test_wave(more[:3], 2)
            messages.append({"role": "user", "content": json.dumps(content, ensure_ascii=False)})
        return messages

    # ----------------------------------------------------------------- final reply
    def finish(self, messages, answer, specs, native, strategy):
        """Validate the final reply; repair by patch when possible, else by full rewrite."""
        raw, allowed = None, None
        while True:
            calls = answer["tool_calls"] if native else []
            if calls:
                issues = [{"at": "$", "code": "TOOLS_CLOSED"}]
                messages.append(self.assistant_entry(answer))
                messages += self.closed_results(calls, native)
            else:
                try:
                    parsed = json.loads(text_of(answer))
                    candidate = patches.apply(raw, parsed, allowed) if allowed else parsed
                    analysis = self.validate(candidate)
                    self.event("validated", repairs=self.repairs)
                    self.final_answer = answer
                    return analysis, candidate
                except EvidenceError as exc:
                    issues = exc.issues
                    raw = candidate
                except (ValueError, TypeError, KeyError, RecursionError, ProviderError):
                    code = "INVALID_PATCH" if allowed else "INVALID_JSON"
                    issues = [{"at": "$", "code": code, "hint": "reply with one JSON object"}]
                if answer.get("content") or answer.get("raw"):
                    messages.append(self.assistant_entry(answer))
            if self.repairs >= self.budgets["repairs"]:
                raise ProviderError("EVIDENCE_VALIDATION_FAILED")
            self.repairs += 1
            allowed = patches.targets(issues) if isinstance(raw, dict) and not calls else None
            self.event(
                "repair", codes=[i["code"] for i in issues][:8], mode="patch" if allowed else "full"
            )
            messages.append(
                {
                    "role": "user",
                    "content": patches.request(issues, allowed)
                    if allowed
                    else self.repair_message(issues),
                }
            )
            answer = self.call(
                messages,
                tools=specs,
                tool_choice="none" if native else None,
                output=self.structured("patch") if allowed else self.output_for(strategy, True),
            )

    def tool_loop(self, strategy, facts):
        """v2 loop: the model calls tools directly, then writes the reply."""
        native = strategy == "native_tools"
        envelope = strategy == "restricted_json"
        specs = tool_specs() if native else None
        messages = self.initial_messages(strategy, facts)
        forced = not (native or envelope)
        self.event("plan", strategy=strategy, goals=len(GOALS.get(self.request.get("intent"), [])))
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
            if not calls or forced:
                return messages, *self.finish(messages, answer, specs, native, strategy)
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
                messages.append(
                    {
                        "role": "user",
                        "content": "Tool results DATA: "
                        + json.dumps([json.loads(c) for _, _, c, _ in results], ensure_ascii=False),
                    }
                )
            reason = (
                "no_new_evidence"
                if not new
                else "round_limit"
                if self.rounds >= self.budgets["tool_rounds"]
                else "budget"
                if self.near_budget()
                else None
            )
            if reason:
                forced = True
                self.event("finalize", reason=reason)
                messages.append(
                    {"role": "user", "content": "Tools are now closed. Reply with the final JSON."}
                )
            self.compact(messages)

    # ----------------------------------------------------------------- review
    def model_review(self, analysis):
        """Independent pass by the configured review model; issues are hints, never verdicts."""
        sentences = [{"at": at, "text": text} for at, text in rendered_sentences(analysis)]
        data = {
            "language": self.language,
            "sentences": sentences,
            "hypotheses": [
                {"id": v["id"], "statement": v["statement"], "state": v["state"]}
                for v in self.verdicts()
            ],
        }
        messages = [
            {"role": "system", "content": load(PROMPT_VERSION, "review")},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ]
        try:
            answer = self.call(
                messages, output=self.structured("review"), model=self.config["review_model_name"]
            )
            parsed = Review.model_validate(json.loads(text_of(answer)))
        except ProviderError as error:
            self.event("review", source="model", error=error.code)
            return []
        except (ValueError, ValidationError, TypeError):
            self.event("review", source="model", error="REVIEW_INVALID")
            return []
        known = {at for at, _ in rendered_sentences(analysis)}
        return [
            {"at": i.at, "code": i.code, "hint": i.note[:120]}
            for i in parsed.issues
            if i.at in known and patches.target(i.at)
        ]

    def review(self, messages, analysis, raw):
        """Lint (and optionally a review model); one patch round when the issues warrant it."""
        found = lint(raw, self.evidence)
        reviewed = []
        # Configs tested before the review probe existed carry no flag: treat them as unusable.
        reviewer = self.config.get("review_model_name") and (
            self.config["capabilities"].get("review_usable") is True
        )
        if reviewer and not self.near_budget():
            reviewed = self.model_review(analysis)
        self.event(
            "review",
            lint=[i["code"] for i in found],
            model=[i["code"] for i in reviewed] if reviewer else None,
        )
        trigger = found or len(reviewed) >= 2 or any(i["code"] in REVIEW_TRIGGERS for i in reviewed)
        issues = (found + reviewed)[:8]
        allowed = patches.targets(issues) if trigger else None
        if not allowed or self.usage["requests"] >= self.budgets["requests"] or self.near_budget():
            return analysis, raw
        if self.final_answer is not None:
            messages.append(self.assistant_entry(self.final_answer))
        messages.append(
            {
                "role": "user",
                "content": "A review of your validated reply found weak spots. "
                + patches.request(issues, allowed),
            }
        )
        applied = False
        try:
            answer = self.call(messages, output=self.structured("patch"))
            candidate = patches.apply(raw, json.loads(text_of(answer)), allowed)
            improved = self.validate(candidate)
            if len(lint(candidate, self.evidence)) <= len(found):
                analysis, raw, applied = improved, candidate, True
        except (ProviderError, EvidenceError, ValueError, TypeError, KeyError, RecursionError):
            pass  # The validated reply stands; review can only improve it.
        self.event("review_repair", applied=applied)
        return analysis, raw

    # ----------------------------------------------------------------- run
    def run(self):
        error, analysis, raw_final = None, None, None
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
                messages = None
                if self.kind == "report" and strategy in HYPOTHESIS_STRATEGIES:
                    messages = self.hypothesis_flow(strategy, facts)
                    if messages is None:
                        self.event("fallback", reason="INVALID_PLAN")
                if messages is not None:
                    answer = self.call(messages, output=self.output_for(strategy, True))
                    analysis, raw_final = self.finish(messages, answer, None, False, strategy)
                else:
                    self.mode = "tools"
                    messages, analysis, raw_final = self.tool_loop(strategy, facts)
                if self.kind == "report":
                    analysis, raw_final = self.review(messages, analysis, raw_final)
            except ProviderError as exc:
                error = exc.code
            except Exception:
                error = "MODEL_OUTPUT_INVALID"
            annotate(
                root,
                {
                    "shoppulse.requests": self.usage["requests"],
                    "shoppulse.tools": self.calls,
                    "shoppulse.tests": self.tests,
                    "shoppulse.repairs": self.repairs,
                    **({"error.type": error} if error else {}),
                },
            )
        if error:
            analysis, raw_final = None, None
        self.event("completed", error=error, repairs=self.repairs, mode=self.mode)
        return {
            "analysis": analysis,
            "raw_analysis": raw_final if analysis else None,
            "error_code": error,
            "repaired": self.repairs > 0,
            "repairs": self.repairs,
            "mode": self.mode,
            "usage": {
                **self.usage,
                "tools": self.calls,
                "tests": self.tests,
                "tool_rounds": self.rounds,
            },
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
