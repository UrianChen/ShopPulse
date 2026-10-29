"""Wire adapters between ShopPulse's neutral conversation and provider protocols.

Neutral entries:
  {"role": "system" | "user", "content": str}
  {"role": "assistant", "content": str | None, "tool_calls": [{"id", "name", "arguments"}],
   "raw": provider-specific replay data}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}

Assistant turns are replayed from ``raw`` when available so the conversation stays append-only
(Anthropic binds thinking blocks to the exact history that produced them).
"""

import json

from app.providers.egress import ProviderError

PROTOCOLS = ("openai_chat", "openai_responses", "anthropic_messages")
ANTHROPIC_VERSION = "2026-10-21"
ANTHROPIC_MAX_TOKENS = 8000
ENDPOINTS = {
    "openai_chat": "/chat/completions",
    "openai_responses": "/responses",
    "anthropic_messages": "/messages",
}


def headers(protocol, key):
    values = {"Content-Type": "application/json", "Accept": "application/json"}
    if protocol == "anthropic_messages":
        values["anthropic-version"] = ANTHROPIC_VERSION
        if key:
            values["x-api-key"] = key
    elif key:
        values["Authorization"] = f"Bearer {key}"
    return values


def _openai_chat(model, messages, tools, tool_choice, output, max_tokens, token_parameter):
    wire = []
    for m in messages:
        if m["role"] == "assistant":
            entry = {"role": "assistant", "content": m.get("content")}
            if m.get("tool_calls"):
                entry["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": json.dumps(c["arguments"], ensure_ascii=False),
                        },
                    }
                    for c in m["tool_calls"]
                ]
            wire.append(entry)
        elif m["role"] == "tool":
            wire.append(
                {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]}
            )
        else:
            wire.append({"role": m["role"], "content": m["content"]})
    payload = {"model": model, "messages": wire}
    if tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]
    if tool_choice == "none" and tools:
        payload["tool_choice"] = "none"
    elif isinstance(tool_choice, dict):
        payload["tool_choice"] = {"type": "function", "function": {"name": tool_choice["name"]}}
    if output and output["type"] == "json_object":
        payload["response_format"] = {"type": "json_object"}
    elif output and output["type"] == "json_schema":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": output["name"], "schema": output["schema"], "strict": True},
        }
    if token_parameter in {"max_tokens", "max_completion_tokens"}:
        payload[token_parameter] = max_tokens
    return payload


def _responses(model, messages, tools, tool_choice, output, max_tokens, token_parameter):
    items, instructions = [], []
    for m in messages:
        if m["role"] == "system":
            instructions.append(m["content"])
        elif m["role"] == "assistant":
            if m.get("raw"):
                items.extend(m["raw"])
                continue
            if m.get("content"):
                items.append({"role": "assistant", "content": m["content"]})
            for c in m.get("tool_calls") or []:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": c["id"],
                        "name": c["name"],
                        "arguments": json.dumps(c["arguments"], ensure_ascii=False),
                    }
                )
        elif m["role"] == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": m["tool_call_id"],
                    "output": m["content"],
                }
            )
        else:
            items.append({"role": "user", "content": m["content"]})
    payload = {"model": model, "input": items, "store": False}
    if instructions:
        payload["instructions"] = "\n\n".join(instructions)
    if tools:
        payload["tools"] = [
            {
                "type": "function",
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in tools
        ]
    if tool_choice == "none" and tools:
        payload["tool_choice"] = "none"
    elif isinstance(tool_choice, dict):
        payload["tool_choice"] = {"type": "function", "name": tool_choice["name"]}
    if output and output["type"] == "json_object":
        payload["text"] = {"format": {"type": "json_object"}}
    elif output and output["type"] == "json_schema":
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": output["name"],
                "schema": output["schema"],
                "strict": True,
            }
        }
    if token_parameter != "none":
        payload["max_output_tokens"] = max_tokens
    return payload


def _anthropic(model, messages, tools, tool_choice, output, max_tokens, token_parameter):
    system, wire = [], []
    pending = []

    def flush():
        if pending:
            wire.append({"role": "user", "content": list(pending)})
            pending.clear()

    for m in messages:
        if m["role"] == "tool":
            pending.append(
                {
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                    **({"is_error": True} if m.get("is_error") else {}),
                }
            )
            continue
        flush()
        if m["role"] == "system":
            system.append(m["content"])
        elif m["role"] == "assistant":
            if m.get("raw"):
                wire.append({"role": "assistant", "content": m["raw"]})
                continue
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            blocks += [
                {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
                for c in m.get("tool_calls") or []
            ]
            wire.append({"role": "assistant", "content": blocks})
        else:
            wire.append({"role": "user", "content": m["content"]})
    flush()
    payload = {
        "model": model,
        "max_tokens": max_tokens if token_parameter != "none" else ANTHROPIC_MAX_TOKENS,
        "messages": wire,
    }
    if system:
        payload["system"] = "\n\n".join(system)
    if tools:
        payload["tools"] = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in tools
        ]
        # Forced tool_choice is rejected by current models; "none" closes the tool round.
        if tool_choice == "none":
            payload["tool_choice"] = {"type": "none"}
    if output and output["type"] == "json_schema":
        payload["output_config"] = {"format": {"type": "json_schema", "schema": output["schema"]}}
    return payload


BUILDERS = {
    "openai_chat": _openai_chat,
    "openai_responses": _responses,
    "anthropic_messages": _anthropic,
}


def build(
    protocol,
    model,
    messages,
    tools=None,
    tool_choice=None,
    output=None,
    max_tokens=1500,
    token_parameter="none",
):
    if protocol not in BUILDERS:
        raise ProviderError("UNSUPPORTED_REQUEST")
    return BUILDERS[protocol](
        model, messages, tools, tool_choice, output, max_tokens, token_parameter
    )


def _arguments(raw):
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _call(identifier, name, arguments):
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200:
        raise ProviderError("INVALID_RESPONSE")
    if not isinstance(name, str) or not 1 <= len(name) <= 64:
        raise ProviderError("INVALID_RESPONSE")
    return {"id": identifier, "name": name, "arguments": _arguments(arguments)}


def _int(value):
    return value if isinstance(value, int) and value >= 0 else 0


def _parse_chat(body):
    try:
        choices = body["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError
        choice = choices[0]
        value = choice["message"]
        if not isinstance(value, dict) or value.get("role") != "assistant":
            raise ValueError
    except (ValueError, KeyError, TypeError, IndexError):
        raise ProviderError("INVALID_RESPONSE") from None
    if value.get("refusal"):
        raise ProviderError("MODEL_REFUSED")
    if choice.get("finish_reason") not in {"stop", "tool_calls"}:
        raise ProviderError("INVALID_RESPONSE")
    calls = []
    for raw in value.get("tool_calls") or []:
        try:
            if raw["type"] != "function":
                raise ValueError
            calls.append(_call(raw["id"], raw["function"]["name"], raw["function"]["arguments"]))
        except (KeyError, TypeError, ValueError):
            raise ProviderError("INVALID_RESPONSE") from None
    content = value.get("content")
    usage = body.get("usage") or {}
    return {
        "content": content if isinstance(content, str) else None,
        "tool_calls": calls,
        "raw": None,
        "usage": {
            "input_tokens": _int(usage.get("prompt_tokens")),
            "output_tokens": _int(usage.get("completion_tokens")),
        },
        # Only what the loop consumes counts toward the output budget; provider extras such as
        # ``reasoning_content`` can be several times larger than the answer itself.
        "visible": {"text": content if isinstance(content, str) else "", "calls": calls},
    }


def _parse_responses(body):
    if body.get("status") not in {"completed", None} or not isinstance(body.get("output"), list):
        raise ProviderError("INVALID_RESPONSE")
    texts, calls, raw = [], [], []
    for item in body["output"]:
        if not isinstance(item, dict):
            raise ProviderError("INVALID_RESPONSE")
        if item.get("type") == "message":
            parts = []
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    raise ProviderError("INVALID_RESPONSE")
                if part.get("type") == "refusal":
                    raise ProviderError("MODEL_REFUSED")
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            texts.extend(parts)
            raw.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": t} for t in parts],
                }
            )
        elif item.get("type") == "function_call":
            call = _call(item.get("call_id"), item.get("name"), item.get("arguments"))
            calls.append(call)
            raw.append(
                {
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": call["name"],
                    "arguments": item.get("arguments")
                    if isinstance(item.get("arguments"), str)
                    else json.dumps(item.get("arguments")),
                }
            )
    usage = body.get("usage") or {}
    return {
        "content": "".join(texts) or None,
        "tool_calls": calls,
        "raw": raw,
        "usage": {
            "input_tokens": _int(usage.get("input_tokens")),
            "output_tokens": _int(usage.get("output_tokens")),
        },
        "visible": {"text": "".join(texts), "calls": calls},
    }


def _parse_anthropic(body):
    if body.get("type") != "message" or body.get("role") != "assistant":
        raise ProviderError("INVALID_RESPONSE")
    reason = body.get("stop_reason")
    if reason == "refusal":
        raise ProviderError("MODEL_REFUSED")
    if reason not in {"end_turn", "tool_use", "stop_sequence"}:
        raise ProviderError("INVALID_RESPONSE")
    content = body.get("content")
    if not isinstance(content, list):
        raise ProviderError("INVALID_RESPONSE")
    texts, calls = [], []
    for block in content:
        if not isinstance(block, dict):
            raise ProviderError("INVALID_RESPONSE")
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        elif block.get("type") == "tool_use":
            calls.append(_call(block.get("id"), block.get("name"), block.get("input")))
    usage = body.get("usage") or {}
    return {
        "content": "".join(texts) or None,
        "tool_calls": calls,
        # Replay every block unchanged, including (possibly empty) thinking blocks.
        "raw": content,
        "usage": {
            "input_tokens": _int(usage.get("input_tokens"))
            + _int(usage.get("cache_read_input_tokens"))
            + _int(usage.get("cache_creation_input_tokens")),
            "output_tokens": _int(usage.get("output_tokens")),
        },
        "visible": {"text": "".join(texts), "calls": calls},
    }


PARSERS = {
    "openai_chat": _parse_chat,
    "openai_responses": _parse_responses,
    "anthropic_messages": _parse_anthropic,
}


def parse(protocol, body):
    if not isinstance(body, dict):
        raise ProviderError("INVALID_RESPONSE")
    return PARSERS[protocol](body)


def text_of(answer):
    content = answer.get("content")
    if not isinstance(content, str) or not content.strip() or answer.get("tool_calls"):
        raise ProviderError("INVALID_RESPONSE")
    return content
