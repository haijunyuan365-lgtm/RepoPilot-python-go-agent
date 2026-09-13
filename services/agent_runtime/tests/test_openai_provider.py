import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.agent import (
    AgentLoop,
    AgentResultStatus,
    AgentState,
    Message,
    MessageRole,
    ToolCall,
    ToolResult,
)
from app.providers import OpenAIChatModel, OpenAIProviderError
from app.tools import Tool, ToolRegistry


class StubHTTPResponse:
    """Small HTTP response double; provider mapping remains the code under test."""

    def __init__(self, payload: object, *, raw: bool = False) -> None:
        if raw:
            self._body = payload
        else:
            self._body = json.dumps(payload).encode("utf-8")
        self.read_limits: list[int] = []

    def __enter__(self) -> "StubHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        self.read_limits.append(limit)
        return self._body if limit < 0 else self._body[:limit]


def response_with_message(message: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


class OpenAIChatModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api_key = "test-key-that-must-stay-private"

    def provider(self, **overrides: object) -> OpenAIChatModel:
        values = {
            "api_key": self.api_key,
            "model": "test-model",
            **overrides,
        }
        return OpenAIChatModel(**values)

    def test_validates_configuration_and_keeps_api_key_out_of_repr(self) -> None:
        provider = self.provider(timeout_seconds=12, max_response_bytes=1024)

        self.assertEqual(provider.model, "test-model")
        self.assertIn("test-model", repr(provider))
        self.assertNotIn(self.api_key, repr(provider))

        invalid_cases = [
            ({"api_key": ""}, "api_key"),
            ({"model": " "}, "model"),
            ({"timeout_seconds": 0}, "timeout_seconds"),
            ({"timeout_seconds": True}, "timeout_seconds"),
            ({"timeout_seconds": float("nan")}, "timeout_seconds"),
            ({"timeout_seconds": float("inf")}, "timeout_seconds"),
            ({"max_response_bytes": 0}, "max_response_bytes"),
            ({"max_response_bytes": 1.5}, "max_response_bytes"),
        ]
        for overrides, expected in invalid_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, expected):
                    self.provider(**overrides)

    def test_from_env_requires_the_api_key_without_echoing_it(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(OpenAIProviderError, "not configured"):
                OpenAIChatModel.from_env(model="test-model")

        with patch.dict(os.environ, {"OPENAI_API_KEY": self.api_key}, clear=True):
            provider = OpenAIChatModel.from_env(model="test-model")

        self.assertNotIn(self.api_key, repr(provider))

    @patch("app.providers.openai_chat.urlopen")
    def test_serializes_messages_tool_observation_and_schema(self, mocked_urlopen) -> None:
        response = StubHTTPResponse(
            response_with_message(
                {"role": "assistant", "content": "修复建议已生成。"}
            )
        )
        mocked_urlopen.return_value = response
        call = ToolCall(
            id="call-1",
            name="read_file",
            arguments={"path": "src/示例.py"},
        )
        result = ToolResult(
            tool_call_id="call-1",
            tool_name="read_file",
            success=False,
            output="partial output",
            error="file was truncated",
            duration_ms=7,
            truncated=True,
        )
        messages = (
            Message(role=MessageRole.SYSTEM, content="You are RepoPilot."),
            Message(role=MessageRole.USER, content="请读取文件。"),
            Message(role=MessageRole.ASSISTANT, tool_calls=(call,)),
            Message(role=MessageRole.TOOL, tool_result=result),
        )
        tools = [
            {
                "name": "read_file",
                "description": "Read one repository file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ]

        message = self.provider().complete(messages, tools)

        self.assertEqual(message.content, "修复建议已生成。")
        request, = mocked_urlopen.call_args.args
        self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 60.0)
        self.assertEqual(
            request.full_url,
            "https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {self.api_key}")
        self.assertNotIn(self.api_key, request.data.decode("utf-8"))
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["content"], "请读取文件。")
        assistant_call = payload["messages"][2]["tool_calls"][0]
        self.assertEqual(assistant_call["id"], "call-1")
        self.assertEqual(
            json.loads(assistant_call["function"]["arguments"]),
            {"path": "src/示例.py"},
        )
        observation = json.loads(payload["messages"][3]["content"])
        self.assertEqual(observation, result.to_dict())
        self.assertEqual(payload["tools"][0]["type"], "function")
        self.assertEqual(
            payload["tools"][0]["function"]["parameters"],
            tools[0]["input_schema"],
        )
        self.assertEqual(response.read_limits, [2_000_001])

    @patch("app.providers.openai_chat.urlopen")
    def test_parses_multiple_function_calls_with_json_object_arguments(
        self,
        mocked_urlopen,
    ) -> None:
        mocked_urlopen.return_value = StubHTTPResponse(
            response_with_message(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "search_code",
                                "arguments": '{"query":"target","path":"src"}',
                            },
                        },
                        {
                            "id": "call-2",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"src/main.py"}',
                            },
                        },
                    ],
                }
            )
        )

        message = self.provider().complete(
            (Message(role=MessageRole.USER, content="Inspect the code."),),
            [],
        )

        self.assertEqual(message.role, MessageRole.ASSISTANT)
        self.assertEqual(message.content, "")
        self.assertEqual(
            [(call.id, call.name) for call in message.tool_calls],
            [("call-1", "search_code"), ("call-2", "read_file")],
        )
        self.assertEqual(message.tool_calls[0].arguments["path"], "src")
        request, = mocked_urlopen.call_args.args
        self.assertNotIn("tools", json.loads(request.data.decode("utf-8")))

    @patch("app.providers.openai_chat.urlopen")
    def test_integrates_with_agent_loop_and_returns_observation_next_turn(
        self,
        mocked_urlopen,
    ) -> None:
        mocked_urlopen.side_effect = [
            StubHTTPResponse(
                response_with_message(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-inspect",
                                "type": "function",
                                "function": {
                                    "name": "inspect",
                                    "arguments": '{"value":"source"}',
                                },
                            }
                        ],
                    }
                )
            ),
            StubHTTPResponse(
                response_with_message(
                    {"role": "assistant", "content": "Inspection complete."}
                )
            ),
        ]

        def inspect(call: ToolCall) -> ToolResult:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                success=True,
                output=f"found:{call.arguments['value']}",
            )

        registry = ToolRegistry(
            [
                Tool(
                    name="inspect",
                    description="Inspect a value.",
                    input_schema={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                    handler=inspect,
                )
            ]
        )
        state = AgentState(
            messages=[Message(role=MessageRole.USER, content="Inspect source.")],
            max_iterations=2,
        )

        result = AgentLoop(model=self.provider(), tools=registry).run(state)

        self.assertEqual(result.status, AgentResultStatus.SUCCEEDED)
        self.assertEqual(result.final_message.content, "Inspection complete.")
        self.assertEqual(result.iterations, 2)
        second_request, = mocked_urlopen.call_args_list[1].args
        second_payload = json.loads(second_request.data.decode("utf-8"))
        observation = json.loads(second_payload["messages"][-1]["content"])
        self.assertTrue(observation["success"])
        self.assertEqual(observation["output"], "found:source")
        self.assertEqual(observation["tool_call_id"], "call-inspect")

    @patch("app.providers.openai_chat.urlopen")
    def test_rejects_invalid_inputs_before_network_io(self, mocked_urlopen) -> None:
        provider = self.provider()
        user_message = Message(role=MessageRole.USER, content="Hello")
        invalid_cases = [
            ([], [], "non-empty tuple"),
            ((), [], "non-empty tuple"),
            (("not-a-message",), [], "Message values"),
            ((user_message,), {}, "tools must be a list"),
            ((user_message,), ["bad"], "tool schema"),
            (
                (user_message,),
                [{"name": "x", "description": "x", "input_schema": {}}],
                "object schema",
            ),
        ]

        for messages, tools, expected in invalid_cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    provider.complete(messages, tools)

        mocked_urlopen.assert_not_called()

    @patch("app.providers.openai_chat.urlopen")
    def test_rejects_oversized_and_invalid_json_responses(self, mocked_urlopen) -> None:
        cases = [
            (
                StubHTTPResponse(b"12345", raw=True),
                {"max_response_bytes": 4},
                "exceeded",
            ),
            (StubHTTPResponse(b"not-json", raw=True), {}, "invalid JSON"),
            (StubHTTPResponse([], raw=False), {}, "JSON object"),
        ]
        for response, overrides, expected in cases:
            with self.subTest(expected=expected):
                mocked_urlopen.return_value = response
                with self.assertRaisesRegex(OpenAIProviderError, expected):
                    self.provider(**overrides).complete(
                        (Message(role=MessageRole.USER, content="Hello"),),
                        [],
                    )

    @patch("app.providers.openai_chat.urlopen")
    def test_rejects_malformed_provider_messages(self, mocked_urlopen) -> None:
        malformed = [
            ({}, "choices"),
            ({"choices": []}, "choices"),
            ({"choices": ["bad"]}, "choice"),
            ({"choices": [{}]}, "message object"),
            (
                response_with_message({"role": "user", "content": "wrong"}),
                "role",
            ),
            (
                response_with_message({"role": "assistant", "content": []}),
                "content",
            ),
            (
                response_with_message(
                    {"role": "assistant", "content": "x", "tool_calls": {}}
                ),
                "tool_calls",
            ),
            (
                response_with_message(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "inspect",
                                    "arguments": "not-json",
                                },
                            }
                        ],
                    }
                ),
                "invalid assistant",
            ),
            (
                response_with_message(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "inspect",
                                    "arguments": "[]",
                                },
                            }
                        ],
                    }
                ),
                "decode to an object",
            ),
            (
                response_with_message({"role": "assistant", "content": None}),
                "requires content or tool_calls",
            ),
        ]

        for payload, expected in malformed:
            with self.subTest(expected=expected):
                mocked_urlopen.return_value = StubHTTPResponse(payload)
                with self.assertRaisesRegex(OpenAIProviderError, expected):
                    self.provider().complete(
                        (Message(role=MessageRole.USER, content="Hello"),),
                        [],
                    )

    @patch("app.providers.openai_chat.urlopen")
    def test_reports_http_error_without_leaking_api_key(self, mocked_urlopen) -> None:
        body = json.dumps(
            {"error": {"message": f"invalid credential {self.api_key}"}}
        ).encode("utf-8")
        mocked_urlopen.side_effect = HTTPError(
            "https://api.openai.com/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(body),
        )

        with self.assertRaises(OpenAIProviderError) as captured:
            self.provider().complete(
                (Message(role=MessageRole.USER, content="Hello"),),
                [],
            )

        error = str(captured.exception)
        self.assertIn("HTTP 401", error)
        self.assertIn("[REDACTED]", error)
        self.assertNotIn(self.api_key, error)

    @patch("app.providers.openai_chat.urlopen")
    def test_reports_network_error_without_leaking_api_key(self, mocked_urlopen) -> None:
        mocked_urlopen.side_effect = URLError(
            f"connection refused for {self.api_key}"
        )

        with self.assertRaises(OpenAIProviderError) as captured:
            self.provider().complete(
                (Message(role=MessageRole.USER, content="Hello"),),
                [],
            )

        error = str(captured.exception)
        self.assertIn("connection refused", error)
        self.assertNotIn(self.api_key, error)


if __name__ == "__main__":
    unittest.main()
