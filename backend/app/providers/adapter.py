"""Small Chat Completions adapter. No provider text enters persisted probe results."""

import json
import time

from app.providers.egress import ProviderError, post

MESSAGES = {
    "AUTH_FAILED": "认证失败，请检查 API Key 与服务权限。",
    "MODEL_NOT_FOUND": "模型或接口不存在，请检查模型名称和 API 根地址。",
    "RATE_LIMITED": "服务限流或额度不足，请稍后重试并检查服务余额。",
    "UNSUPPORTED_REQUEST": "服务不支持此请求参数或能力。",
    "PROVIDER_UNAVAILABLE": "模型服务暂不可用。",
    "PROVIDER_REJECTED": "模型服务拒绝了请求。",
    "INVALID_RESPONSE": "服务响应未通过格式校验。",
    "INVALID_BASE_URL": "请填写 API 根地址，不含凭证、查询参数或 chat/completions。",
    "EGRESS_BLOCKED": "目标地址被出站策略阻止；本地服务需由部署者配置精确来源白名单。",
    "REDIRECT_BLOCKED": "服务返回重定向，请使用最终 API 根地址。",
    "DNS_FAILED": "无法解析模型服务域名。",
    "TLS_FAILED": "服务的 HTTPS 证书校验失败。",
    "NETWORK_ERROR": "无法连接模型服务。",
    "TIMEOUT": "模型请求超时。",
    "BUDGET_EXCEEDED": "连接测试已达到时间或请求次数上限。",
    "RESPONSE_TOO_LARGE": "模型响应超过大小限制。",
    "CREDENTIAL_UNAVAILABLE": "后端无法解密凭证，请检查主密钥。",
}


def failure(error):
    return {
        "ok": False,
        "code": error.code,
        "http_status": error.status,
        "message": MESSAGES.get(error.code, "连接测试失败。"),
    }


def message(body):
    try:
        choices = body["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError
        choice = choices[0]
        value = choice["message"]
        if not isinstance(value, dict) or value.get("role") != "assistant":
            raise ValueError
        if choice.get("finish_reason") not in {"stop", "tool_calls"} or value.get("refusal"):
            raise ValueError
        return value
    except (ValueError, KeyError, TypeError, IndexError):
        raise ProviderError("INVALID_RESPONSE") from None


def text_content(value):
    content = value.get("content")
    if not isinstance(content, str) or not content.strip() or value.get("tool_calls"):
        raise ProviderError("INVALID_RESPONSE")
    return content


class ProviderAdapter:
    def __init__(self, config, key, transport=post):
        self.config, self.key, self.transport = config, key, transport
        self.deadline = time.monotonic() + 85
        self.requests = 0

    def complete(self, messages, **options):
        payload = {"model": self.config["model_name"], "messages": messages, **options}
        parameter = self.config.get("token_limit_parameter", "none")
        if parameter in {"max_tokens", "max_completion_tokens"}:
            payload[parameter] = 256
        for attempt in range(2):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or self.requests >= 6:
                raise ProviderError("BUDGET_EXCEEDED")
            self.requests += 1
            try:
                body = self.transport(
                    self.config["base_url"],
                    self.key,
                    payload,
                    min(self.config["timeout_seconds"], remaining),
                )
                return message(body)
            except ProviderError as error:
                if attempt == 0 and error.code in {"RATE_LIMITED", "PROVIDER_UNAVAILABLE"}:
                    time.sleep(0.25)
                    continue
                raise

    def probe(self):
        stages = {}

        def run(name, operation):
            try:
                operation()
                stages[name] = {
                    "ok": True,
                    "code": "OK",
                    "message": "验证通过。",
                    "http_status": 200,
                }
            except ProviderError as error:
                stages[name] = failure(error)
            return stages[name]["ok"]

        if not run(
            "basic",
            lambda: text_content(
                self.complete(
                    [
                        {
                            "role": "user",
                            "content": "Reply with just OK. This is a synthetic connection test.",
                        }
                    ]
                )
            ),
        ):
            return {
                "usable": False,
                "strategy": "unavailable",
                "stages": stages,
                "requests": self.requests,
            }

        def tools_probe():
            messages = [{"role": "user", "content": "Call echo_probe with token pulse-test."}]
            tool = {
                "type": "function",
                "function": {
                    "name": "echo_probe",
                    "description": "Synthetic echo",
                    "parameters": {
                        "type": "object",
                        "properties": {"token": {"type": "string"}},
                        "required": ["token"],
                        "additionalProperties": False,
                    },
                },
            }
            response = self.complete(
                messages,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "echo_probe"}},
            )
            try:
                calls = response["tool_calls"]
                call = calls[0]
                if (
                    len(calls) != 1
                    or call["type"] != "function"
                    or call["function"]["name"] != "echo_probe"
                    or not isinstance(call["id"], str)
                    or not 1 <= len(call["id"]) <= 200
                    or json.loads(call["function"]["arguments"]) != {"token": "pulse-test"}
                ):
                    raise ValueError
                # Only forward validated fields, never arbitrary provider metadata.
                messages += [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": "echo_probe",
                                    "arguments": '{"token":"pulse-test"}',
                                },
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": call["id"], "content": '{"ok":true}'},
                ]
            except (ValueError, KeyError, IndexError, TypeError):
                raise ProviderError("INVALID_RESPONSE") from None
            text_content(self.complete(messages, tools=[tool], tool_choice="none"))

        native_tools = run("tools", tools_probe)
        json_messages = [
            {
                "role": "user",
                "content": 'Return exactly this JSON object: {"ok":true}. No other text.',
            }
        ]

        def json_probe(native):
            options = {"response_format": {"type": "json_object"}} if native else {}
            try:
                value = json.loads(text_content(self.complete(json_messages, **options)))
                if not isinstance(value, dict) or set(value) != {"ok"} or value["ok"] is not True:
                    raise ValueError
            except (ValueError, TypeError):
                raise ProviderError("INVALID_RESPONSE") from None

        native_json = run("json", lambda: json_probe(True))
        text_json = native_json or run("text_json", lambda: json_probe(False))
        return {
            "usable": True,
            "strategy": "native_tools"
            if native_tools
            else "restricted_json"
            if text_json
            else "narrative",
            "native_tools": native_tools,
            "native_json": native_json,
            "text_json": text_json,
            "stages": stages,
            "requests": self.requests,
        }
