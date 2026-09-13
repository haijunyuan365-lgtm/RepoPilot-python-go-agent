import unittest
from typing import Any

from app.tools import Tool, ToolRegistry
from app.agent import (
    AgentLoop,
    AgentResultStatus,
    AgentState,
    Message,
    MessageRole,
    ToolCall,
    ToolResult,
)


class ScriptedChatModel:
    """Deterministic test double for the provider boundary only."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.requests: list[
            tuple[tuple[Message, ...], list[dict[str, Any]]]
        ] = []

    def complete(
        self,
        messages: tuple[Message, ...],
        tools: list[dict[str, Any]],
    ) -> Message:
        self.requests.append((messages, tools))
        if not self._responses:
            raise AssertionError("scripted model received an unexpected request")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[return-value]


def assistant_tool_call(*calls: ToolCall) -> Message:
    return Message(role=MessageRole.ASSISTANT, tool_calls=calls)


def successful_tool(
    name: str,
    executions: list[str],
    *,
    output_prefix: str = "result",
) -> Tool:
    def handler(call: ToolCall) -> ToolResult:
        executions.append(call.id)
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            success=True,
            output=f"{output_prefix}:{call.arguments.get('value', '')}",
        )

    return Tool(
        name=name,
        description=f"Execute {name}.",
        input_schema={"type": "object"},
        handler=handler,
    )


class AgentLoopTests(unittest.TestCase):
    def test_executes_one_tool_and_returns_the_natural_final_answer(self) -> None:
        call = ToolCall(id="call-1", name="inspect", arguments={"value": "source"})
        final = Message(role=MessageRole.ASSISTANT, content="Inspection complete.")
        model = ScriptedChatModel([assistant_tool_call(call), final])
        executions: list[str] = []
        loop = AgentLoop(
            model=model,
            tools=ToolRegistry([successful_tool("inspect", executions)]),
        )
        state = AgentState(
            messages=[Message(role=MessageRole.USER, content="Inspect the code.")],
            max_iterations=3,
        )

        result = loop.run(state)

        self.assertEqual(result.status, AgentResultStatus.SUCCEEDED)
        self.assertEqual(result.final_message, final)
        self.assertEqual(result.iterations, 2)
        self.assertEqual(state.iteration, 2)
        self.assertEqual(executions, ["call-1"])
        self.assertEqual(
            [message.role for message in state.messages],
            [
                MessageRole.USER,
                MessageRole.ASSISTANT,
                MessageRole.TOOL,
                MessageRole.ASSISTANT,
            ],
        )
        observation = state.messages[2].tool_result
        self.assertIsNotNone(observation)
        self.assertEqual(observation.output, "result:source")
        self.assertEqual(model.requests[1][0][-1], state.messages[2])
        self.assertEqual(model.requests[0][1][0]["name"], "inspect")

    def test_executes_multiple_calls_in_order_before_the_next_model_turn(self) -> None:
        calls = (
            ToolCall(id="call-1", name="inspect", arguments={"value": "a"}),
            ToolCall(id="call-2", name="inspect", arguments={"value": "b"}),
        )
        model = ScriptedChatModel(
            [
                assistant_tool_call(*calls),
                Message(role=MessageRole.ASSISTANT, content="Both calls complete."),
            ]
        )
        executions: list[str] = []
        loop = AgentLoop(
            model=model,
            tools=ToolRegistry([successful_tool("inspect", executions)]),
        )
        state = AgentState(
            messages=[Message(role=MessageRole.USER, content="Inspect both inputs.")]
        )

        result = loop.run(state)

        self.assertEqual(result.status, AgentResultStatus.SUCCEEDED)
        self.assertEqual(executions, ["call-1", "call-2"])
        second_turn = model.requests[1][0]
        self.assertEqual(
            [message.tool_result.tool_call_id for message in second_turn[-2:]],
            ["call-1", "call-2"],
        )

    def test_failed_tool_result_is_an_observation_not_a_loop_failure(self) -> None:
        call = ToolCall(id="call-1", name="run_check")

        def failing_check(request: ToolCall) -> ToolResult:
            return ToolResult(
                tool_call_id=request.id,
                tool_name=request.name,
                success=False,
                output="assertion failed",
                error="check exited with code 1",
            )

        model = ScriptedChatModel(
            [
                assistant_tool_call(call),
                Message(role=MessageRole.ASSISTANT, content="I saw the failed check."),
            ]
        )
        loop = AgentLoop(
            model=model,
            tools=ToolRegistry(
                [
                    Tool(
                        name="run_check",
                        description="Run a fake unit check.",
                        input_schema={"type": "object"},
                        handler=failing_check,
                    )
                ]
            ),
        )
        state = AgentState(
            messages=[Message(role=MessageRole.USER, content="Run the check.")]
        )

        result = loop.run(state)

        self.assertEqual(result.status, AgentResultStatus.SUCCEEDED)
        observed = model.requests[1][0][-1].tool_result
        self.assertFalse(observed.success)
        self.assertEqual(observed.error, "check exited with code 1")
        self.assertEqual(observed.output, "assertion failed")

    def test_unknown_tool_becomes_a_correlated_failure_observation(self) -> None:
        call = ToolCall(id="call-404", name="missing_tool")
        model = ScriptedChatModel(
            [
                assistant_tool_call(call),
                Message(role=MessageRole.ASSISTANT, content="The tool is unavailable."),
            ]
        )
        state = AgentState(
            messages=[Message(role=MessageRole.USER, content="Use the missing tool.")]
        )

        result = AgentLoop(model=model, tools=ToolRegistry()).run(state)

        self.assertEqual(result.status, AgentResultStatus.SUCCEEDED)
        observed = model.requests[1][0][-1].tool_result
        self.assertEqual(observed.tool_call_id, "call-404")
        self.assertEqual(observed.tool_name, "missing_tool")
        self.assertFalse(observed.success)
        self.assertIn("unknown tool", observed.error)

    def test_handler_exception_and_invalid_result_become_observations(self) -> None:
        def raises_error(call: ToolCall) -> ToolResult:
            raise RuntimeError("boom")

        def wrong_result(call: ToolCall) -> ToolResult:
            return ToolResult(
                tool_call_id="different-call",
                tool_name=call.name,
                success=True,
                output="wrong",
            )

        cases = [
            ("raises", raises_error, "RuntimeError: boom"),
            ("wrong_result", wrong_result, "different tool call"),
            ("non_result", lambda call: "not structured", "must return a ToolResult"),
        ]

        for name, handler, expected_error in cases:
            with self.subTest(name=name):
                call = ToolCall(id=f"call-{name}", name=name)
                model = ScriptedChatModel(
                    [
                        assistant_tool_call(call),
                        Message(role=MessageRole.ASSISTANT, content="Recovered."),
                    ]
                )
                tool = Tool(
                    name=name,
                    description=f"Exercise {name}.",
                    input_schema={"type": "object"},
                    handler=handler,
                )
                result = AgentLoop(
                    model=model,
                    tools=ToolRegistry([tool]),
                ).run(
                    AgentState(
                        messages=[Message(role=MessageRole.USER, content="Exercise it.")]
                    )
                )

                self.assertEqual(result.status, AgentResultStatus.SUCCEEDED)
                observed = model.requests[1][0][-1].tool_result
                self.assertFalse(observed.success)
                self.assertIn(expected_error, observed.error)

    def test_exhausts_after_the_last_allowed_model_turn(self) -> None:
        calls = [
            ToolCall(id="call-1", name="inspect"),
            ToolCall(id="call-2", name="inspect"),
        ]
        model = ScriptedChatModel([assistant_tool_call(call) for call in calls])
        executions: list[str] = []
        state = AgentState(
            messages=[Message(role=MessageRole.USER, content="Keep inspecting.")],
            max_iterations=2,
        )

        result = AgentLoop(
            model=model,
            tools=ToolRegistry([successful_tool("inspect", executions)]),
        ).run(state)

        self.assertEqual(result.status, AgentResultStatus.EXHAUSTED)
        self.assertEqual(result.iterations, 2)
        self.assertIsNone(result.final_message)
        self.assertEqual(executions, ["call-1", "call-2"])
        self.assertEqual(state.pending_tool_calls, ())
        self.assertEqual(state.messages[-1].tool_result.tool_call_id, "call-2")
        self.assertEqual(len(model.requests), 2)

    def test_model_failure_and_protocol_errors_fail_explicitly(self) -> None:
        cases = [
            ([RuntimeError("provider unavailable")], "provider unavailable"),
            (["not a message"], "must return a Message"),
            (
                [Message(role=MessageRole.USER, content="wrong role")],
                "assistant Message",
            ),
        ]

        for responses, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                state = AgentState(
                    messages=[Message(role=MessageRole.USER, content="Start.")]
                )
                result = AgentLoop(
                    model=ScriptedChatModel(responses),
                    tools=ToolRegistry(),
                ).run(state)

                self.assertEqual(result.status, AgentResultStatus.FAILED)
                self.assertEqual(result.iterations, 1)
                self.assertIn(expected_error, result.error)

    def test_rejects_a_state_with_unresolved_calls_without_running(self) -> None:
        pending = ToolCall(id="call-pending", name="inspect")
        state = AgentState(messages=[assistant_tool_call(pending)], iteration=1)
        model = ScriptedChatModel([])

        result = AgentLoop(model=model, tools=ToolRegistry()).run(state)

        self.assertEqual(result.status, AgentResultStatus.FAILED)
        self.assertEqual(result.iterations, 1)
        self.assertIn("unresolved tool calls", result.error)
        self.assertEqual(model.requests, [])


if __name__ == "__main__":
    unittest.main()
