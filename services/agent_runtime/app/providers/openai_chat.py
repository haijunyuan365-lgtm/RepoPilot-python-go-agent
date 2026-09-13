"""OpenAI Chat Completions adapter for RepoPilot's provider-neutral loop."""

from __future__ import annotations

import json
import math
import os
import socket
from collections.abc import Mapping
from copy import deepcopy
from http.client import HTTPResponse
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agent.models import Message, MessageRole, ToolCall


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
MAX_ERROR_MESSAGE_CHARS = 500


class OpenAIProviderError(RuntimeError):
    """A safe, explicit failure at the OpenAI provider boundary."""


class OpenAIChatModel:
    """Synchronous OpenAI implementation of the runtime ``ChatModel`` contract.

    The adapter deliberately owns only provider translation and one HTTP call.
    Agent iterations, tool execution, retry policy, and task state remain in
    their existing layers.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self._api_key = _require_non_empty(api_key, "api_key")
        self._model = _require_non_empty(model, "model")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive number")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive integer")
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes

    @classmethod
    def from_env(
        cls,
        *,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> "OpenAIChatModel":
        """Build an adapter from ``OPENAI_API_KEY`` without exposing the key."""

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key.strip():
            raise OpenAIProviderError("OPENAI_API_KEY is not configured")
        return cls(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )

    @property
    def model(self) -> str:
        return self._model

    def __repr__(self) -> str:
        # API Key 只保存在私有字段中；调试输出绝不能把密钥带入日志。
        return (
            f"{type(self).__name__}(model={self._model!r}, "
            f"timeout_seconds={self._timeout_seconds!r})"
        )

    def complete(
        self,
        messages: tuple[Message, ...],
        tools: list[dict[str, Any]],
    ) -> Message:
        """Return one provider response as an internal assistant ``Message``."""

        request_payload = self._build_request(messages, tools)
        response_payload = self._post_json(request_payload)
        return self._parse_response(response_payload)

    def _build_request(
        self,
        messages: tuple[Message, ...],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(messages, tuple) or not messages or any(
            not isinstance(message, Message) for message in messages
        ):
            raise ValueError("messages must be a non-empty tuple of Message values")
        if not isinstance(tools, list):
            raise ValueError("tools must be a list")

        # 在 Provider 边界集中转换，避免 OpenAI 字段渗透进核心 Message 模型。
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_to_openai_message(message) for message in messages],
        }
        if tools:
            payload["tools"] = [_to_openai_tool(tool) for tool in tools]
        return payload

    def _post_json(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            OPENAI_CHAT_COMPLETIONS_URL,
            data=encoded,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "RepoPilot/phase-1.8",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = self._read_bounded(response)
        except HTTPError as exc:
            body = exc.read(self._max_response_bytes + 1)
            detail = self._safe_http_error_detail(body)
            raise OpenAIProviderError(
                f"OpenAI request failed with HTTP {exc.code}: {detail}"
            ) from None
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            detail = self._redact(str(getattr(exc, "reason", exc)))
            raise OpenAIProviderError(f"OpenAI request failed: {detail}") from None

        try:
            decoded = body.decode("utf-8")
            data = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenAIProviderError(
                f"OpenAI returned invalid JSON: {type(exc).__name__}"
            ) from None
        if not isinstance(data, Mapping):
            raise OpenAIProviderError("OpenAI response must be a JSON object")
        return data

    def _read_bounded(self, response: HTTPResponse) -> bytes:
        body = response.read(self._max_response_bytes + 1)
        if len(body) > self._max_response_bytes:
            raise OpenAIProviderError(
                "OpenAI response exceeded max_response_bytes"
            )
        return body

    def _safe_http_error_detail(self, body: bytes) -> str:
        if len(body) > self._max_response_bytes:
            return "response body exceeded max_response_bytes"
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "provider returned a non-JSON error body"

        message = "provider returned an error"
        if isinstance(payload, Mapping):
            error = payload.get("error")
            if isinstance(error, Mapping) and isinstance(error.get("message"), str):
                message = error["message"]
        return self._redact(message[:MAX_ERROR_MESSAGE_CHARS])

    def _redact(self, value: str) -> str:
        return value.replace(self._api_key, "[REDACTED]")

    @staticmethod
    def _parse_response(payload: Mapping[str, Any]) -> Message:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenAIProviderError(
                "OpenAI response requires a non-empty choices array"
            )
        first_choice = choices[0]
        if not isinstance(first_choice, Mapping):
            raise OpenAIProviderError("OpenAI choice must be a JSON object")
        raw_message = first_choice.get("message")
        if not isinstance(raw_message, Mapping):
            raise OpenAIProviderError("OpenAI choice requires a message object")
        if raw_message.get("role") != "assistant":
            raise OpenAIProviderError(
                "OpenAI response message role must be 'assistant'"
            )

        content = raw_message.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise OpenAIProviderError(
                "OpenAI response message content must be a string or null"
            )

        raw_calls = raw_message.get("tool_calls")
        if raw_calls is None:
            raw_calls = []
        if not isinstance(raw_calls, list):
            raise OpenAIProviderError(
                "OpenAI response tool_calls must be an array or null"
            )

        try:
            # arguments 是 JSON 字符串；先解析成对象，再交给 ToolCall 校验并冻结。
            tool_calls = tuple(_parse_openai_tool_call(call) for call in raw_calls)
            return Message(
                role=MessageRole.ASSISTANT,
                content=content,
                tool_calls=tool_calls,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenAIProviderError(
                f"OpenAI returned an invalid assistant message: {exc}"
            ) from None


def _require_non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _to_openai_message(message: Message) -> dict[str, Any]:
    if message.role in (MessageRole.SYSTEM, MessageRole.USER):
        return {"role": message.role.value, "content": message.content}

    if message.role is MessageRole.ASSISTANT:
        converted: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or None,
        }
        if message.tool_calls:
            converted["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        return converted

    result = message.tool_result
    if result is None:  # Message 自身会阻止该状态，此分支用于防御未来模型变化。
        raise ValueError("a tool Message requires tool_result")
    # Observation 整体序列化，确保 success/error/截断等证据都回到下一轮模型。
    return {
        "role": "tool",
        "tool_call_id": result.tool_call_id,
        "content": json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }


def _to_openai_tool(tool: object) -> dict[str, Any]:
    if not isinstance(tool, Mapping):
        raise ValueError("each tool schema must be an object")
    name = _require_non_empty(tool.get("name"), "tool.name")
    description = _require_non_empty(tool.get("description"), "tool.description")
    input_schema = tool.get("input_schema")
    if not isinstance(input_schema, Mapping) or input_schema.get("type") != "object":
        raise ValueError("tool.input_schema must be an object schema")
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": deepcopy(dict(input_schema)),
        },
    }


def _parse_openai_tool_call(raw_call: object) -> ToolCall:
    if not isinstance(raw_call, Mapping):
        raise ValueError("each tool call must be an object")
    if raw_call.get("type") != "function":
        raise ValueError("tool call type must be 'function'")
    function = raw_call.get("function")
    if not isinstance(function, Mapping):
        raise ValueError("tool call requires a function object")
    arguments_json = function.get("arguments")
    if not isinstance(arguments_json, str):
        raise ValueError("tool call arguments must be a JSON string")
    arguments = json.loads(arguments_json)
    if not isinstance(arguments, dict):
        raise ValueError("tool call arguments must decode to an object")
    return ToolCall(
        id=raw_call.get("id"),
        name=function.get("name"),
        arguments=arguments,
    )
