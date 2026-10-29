"""Protocol-aware connection probe. No provider text enters persisted probe results."""

import json
import time

from app.providers.egress import ProviderError, post
from app.providers.protocols import build, parse, text_of

MESSAGES = {
    "AUTH_FAILED": "认证失败，请检查 API Key 与服务权限。",
    "MODEL_NOT_FOUND": "模型或接口不存在，请检查模型名称和 API 根地址。",
    "RATE_LIMITED": "服务限流或额度不足，请稍后重试并检查服务余额。",
    "UNSUPPORTED_REQUEST": "服务不支持此请求参数或能力。",
    "PROVIDER_UNAVAILABLE": "模型服务暂不可用。",
    "PROVIDER_REJECTED": "模型服务拒绝了请求。",
    "MODEL_REFUSED": "模型拒绝回答此请求。",
    "INVALID_RESPONSE": "服务响应未通过格式校验。",
    "INVALID_BASE_URL": "请填写 API 根地址，不含凭证、查询参数或具体接口路径。",
    "INVALID_WEBHOOK_URL": "请填写完整的 HTTPS 通知地址，不含账号密码。",
    "WEBHOOK_REJECTED": "通知地址拒绝了请求。",
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
PROBE_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
ECHO_TOOL = {
    "name": "echo_probe",
    "description": "Synthetic echo",
    "parameters": {
        "type": "object",
        "properties": {"token": {"type": "string"}},
        "required": ["token"],
        "additionalProperties": False,
    },
}


def failure(error):
    return {
        "ok": False,
        "code": error.code,
        "http_status": error.status,
        "message": MESSAGES.get(error.code, "连接测试失败。"),
    }


def message(body):
    """v1 helper: validate an OpenAI Chat body and return its assistant message."""
    return parse("openai_chat", body)["visible"]


def text_content(value):
    return text_of(value)


class ProviderAdapter:
    def __init__(self, config, key, transport=post):
        self.config, self.key, self.transport = config, key, transport
        self.protocol = config.get("protocol") or "openai_chat"
        self.deadline = time.monotonic() + 100
        self.requests = 0

    def complete(self, messages, tools=None, tool_choice=None, output=None):
        payload = build(
            self.protocol,
            self.config["model_name"],
            messages,
            tools=tools,
            tool_choice=tool_choice,
            output=output,
            max_tokens=256 if self.protocol != "anthropic_messages" else 2048,
            token_parameter=self.config.get("token_limit_parameter", "none"),
        )
        for attempt in range(2):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or self.requests >= 8:
                raise ProviderError("BUDGET_EXCEEDED")
            self.requests += 1
            try:
                body = self.transport(
                    self.config["base_url"],
                    self.key,
                    payload,
                    min(self.config["timeout_seconds"], remaining),
                    protocol=self.protocol,
                )
                return parse(self.protocol, body)
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

        basic = [
            {"role": "user", "content": "Reply with just OK. This is a synthetic connection test."}
        ]
        if not run("basic", lambda: text_of(self.complete(basic))):
            return {
                "usable": False,
                "strategy": "unavailable",
                "protocol": self.protocol,
                "stages": stages,
                "requests": self.requests,
            }

        def tools_probe():
            messages = [
                {"role": "user", "content": "Call the echo_probe tool with token pulse-test."}
            ]
            # Current Anthropic models reject forced tool_choice; ask for the call instead.
            forced = None if self.protocol == "anthropic_messages" else {"name": "echo_probe"}
            response = self.complete(messages, tools=[ECHO_TOOL], tool_choice=forced)
            calls = response["tool_calls"]
            if (
                len(calls) != 1
                or calls[0]["name"] != "echo_probe"
                or calls[0]["arguments"] != {"token": "pulse-test"}
            ):
                raise ProviderError("INVALID_RESPONSE")
            messages += [
                {
                    "role": "assistant",
                    "content": response["content"],
                    "tool_calls": [
                        {
                            "id": calls[0]["id"],
                            "name": "echo_probe",
                            "arguments": {"token": "pulse-test"},
                        }
                    ],
                    "raw": response["raw"],
                },
                {
                    "role": "tool",
                    "tool_call_id": calls[0]["id"],
                    "name": "echo_probe",
                    "content": '{"ok":true}',
                },
            ]
            text_of(self.complete(messages, tools=[ECHO_TOOL], tool_choice="none"))

        native_tools = run("tools", tools_probe)
        json_messages = [
            {
                "role": "user",
                "content": 'Return exactly this JSON object: {"ok":true}. No other text.',
            }
        ]

        def json_probe(output):
            try:
                value = json.loads(text_of(self.complete(json_messages, output=output)))
                if not isinstance(value, dict) or set(value) != {"ok"} or value["ok"] is not True:
                    raise ValueError
            except (ValueError, TypeError):
                raise ProviderError("INVALID_RESPONSE") from None

        native_json = False
        if self.protocol != "anthropic_messages":
            native_json = run("json", lambda: json_probe({"type": "json_object"}))
        json_schema = run(
            "json_schema",
            lambda: json_probe({"type": "json_schema", "name": "probe", "schema": PROBE_SCHEMA}),
        )
        text_json = native_json or json_schema or run("text_json", lambda: json_probe(None))
        return {
            "usable": True,
            "protocol": self.protocol,
            "strategy": "native_tools"
            if native_tools
            else "restricted_json"
            if text_json
            else "narrative",
            "native_tools": native_tools,
            "native_json": native_json,
            "json_schema": json_schema,
            "text_json": text_json,
            "stages": stages,
            "requests": self.requests,
        }
