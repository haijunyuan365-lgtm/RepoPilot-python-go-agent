import json
import math
import unittest

from app.agent.models import (
    AgentResult,
    AgentResultStatus,
    AgentState,
    Message,
    MessageRole,
    ToolCall,
    ToolResult,
)


def assistant_call(call_id: str = "call-1", name: str = "read_file") -> Message:
    return Message(
        role=MessageRole.ASSISTANT,
        tool_calls=(ToolCall(id=call_id, name=name, arguments={"path": "src/app.py"}),),
    )


def tool_message(
    call_id: str = "call-1",
    name: str = "read_file",
    *,
    success: bool = True,
) -> Message:
    return Message(
        role=MessageRole.TOOL,
        tool_result=ToolResult(
            tool_call_id=call_id,
            tool_name=name,
            success=success,
            output="source" if success else "",
            error=None if success else "file not found",
            duration_ms=3,
        ),
    )


class ToolCallTests(unittest.TestCase):
    def test_round_trip_detaches_json_arguments(self) -> None:
        arguments = {"path": "src/app.py", "lines": [1, 2], "options": {"raw": True}}
        call = ToolCall(id="call-1", name="read_file", arguments=arguments)

        arguments["lines"].append(3)
        encoded = call.to_dict()
        encoded["arguments"]["options"]["raw"] = False

        self.assertEqual(call.arguments["lines"], [1, 2])
        self.assertEqual(call.arguments["options"], {"raw": True})
        self.assertEqual(ToolCall.from_dict(call.to_dict()), call)
        self.assertEqual(json.loads(json.dumps(call.to_dict())), call.to_dict())

    def test_rejects_empty_identifiers_and_non_json_arguments(self) -> None:
        with self.assertRaisesRegex(ValueError, "ToolCall.id"):
            ToolCall(id=" ", name="read_file")
        with self.assertRaisesRegex(ValueError, "ToolCall.name"):
            ToolCall(id="call-1", name="")
        with self.assertRaisesRegex(ValueError, "keys must be strings"):
            ToolCall(id="call-1", name="read_file", arguments={1: "bad"})
        with self.assertRaisesRegex(ValueError, "non-JSON"):
            ToolCall(id="call-1", name="read_file", arguments={"paths": {"a.py"}})
        with self.assertRaisesRegex(ValueError, "NaN or infinity"):
            ToolCall(id="call-1", name="read_file", arguments={"limit": math.nan})


class ToolResultTests(unittest.TestCase):
    def test_success_and_failure_round_trip(self) -> None:
        succeeded = ToolResult(
            tool_call_id="call-1",
            tool_name="run_test",
            success=True,
            output="1 passed",
            duration_ms=18,
        )
        failed = ToolResult(
            tool_call_id="call-2",
            tool_name="run_test",
            success=False,
            output="AssertionError",
            error="test command exited with code 1",
            duration_ms=20,
            truncated=True,
        )

        self.assertEqual(ToolResult.from_dict(succeeded.to_dict()), succeeded)
        self.assertEqual(ToolResult.from_dict(failed.to_dict()), failed)

    def test_rejects_inconsistent_success_and_error_states(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not contain an error"):
            ToolResult(
                tool_call_id="call-1",
                tool_name="run_test",
                success=True,
                error="contradiction",
            )
        with self.assertRaisesRegex(ValueError, "failed ToolResult.error"):
            ToolResult(tool_call_id="call-1", tool_name="run_test", success=False)
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            ToolResult(
                tool_call_id="call-1",
                tool_name="run_test",
                success=False,
                error="timeout",
                duration_ms=-1,
            )


class MessageTests(unittest.TestCase):
    def test_each_role_round_trips(self) -> None:
        messages = [
            Message(role="system", content="You are RepoPilot."),
            Message(role="user", content="Read the failing module."),
            assistant_call(),
            tool_message(),
            Message(role="assistant", content="The file has been inspected."),
        ]

        for message in messages:
            with self.subTest(role=message.role):
                self.assertEqual(Message.from_dict(message.to_dict()), message)

    def test_rejects_role_payload_mismatches(self) -> None:
        with self.assertRaisesRegex(ValueError, "user Message requires content"):
            Message(role=MessageRole.USER)
        with self.assertRaisesRegex(ValueError, "assistant Message requires"):
            Message(role=MessageRole.ASSISTANT)
        with self.assertRaisesRegex(ValueError, "only an assistant"):
            Message(
                role=MessageRole.USER,
                content="bad",
                tool_calls=(ToolCall(id="call-1", name="read_file"),),
            )
        with self.assertRaisesRegex(ValueError, "requires tool_result"):
            Message(role=MessageRole.TOOL)
        with self.assertRaisesRegex(ValueError, "cannot contain content"):
            Message(
                role=MessageRole.TOOL,
                content="duplicate payload",
                tool_result=tool_message().tool_result,
            )

    def test_rejects_duplicate_tool_call_ids_within_one_message(self) -> None:
        call = ToolCall(id="call-1", name="read_file")
        with self.assertRaisesRegex(ValueError, "duplicate ids"):
            Message(role=MessageRole.ASSISTANT, tool_calls=(call, call))


class AgentStateTests(unittest.TestCase):
    def test_tracks_pending_calls_and_round_trips_a_valid_transcript(self) -> None:
        first_call = ToolCall(id="call-1", name="read_file", arguments={"path": "a.py"})
        second_call = ToolCall(id="call-2", name="search_code", arguments={"query": "bug"})
        state = AgentState(
            messages=[
                Message(role=MessageRole.USER, content="Find the bug."),
                Message(role=MessageRole.ASSISTANT, tool_calls=(first_call, second_call)),
                Message(
                    role=MessageRole.TOOL,
                    tool_result=ToolResult(
                        tool_call_id="call-1",
                        tool_name="read_file",
                        success=True,
                        output="source",
                    ),
                ),
            ],
            iteration=1,
            max_iterations=4,
        )

        self.assertEqual(state.pending_tool_calls, (second_call,))
        self.assertEqual(AgentState.from_dict(state.to_dict()), state)
        self.assertEqual(json.loads(json.dumps(state.to_dict())), state.to_dict())

    def test_append_message_preserves_state_when_association_is_invalid(self) -> None:
        state = AgentState(messages=[assistant_call()])

        with self.assertRaisesRegex(ValueError, "earlier unresolved ToolCall"):
            state.append_message(tool_message(call_id="unknown"))

        self.assertEqual(len(state.messages), 1)
        self.assertEqual(state.pending_tool_calls[0].id, "call-1")

    def test_rejects_mismatched_tool_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            AgentState(messages=[assistant_call(), tool_message(name="search_code")])

    def test_rejects_duplicate_call_ids_across_messages(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate tool call id"):
            AgentState(messages=[assistant_call(), assistant_call()])

    def test_rejects_a_second_result_for_the_same_call(self) -> None:
        with self.assertRaisesRegex(ValueError, "earlier unresolved ToolCall"):
            AgentState(messages=[assistant_call(), tool_message(), tool_message()])

    def test_advances_until_iteration_budget_is_exhausted(self) -> None:
        state = AgentState(max_iterations=2)

        self.assertEqual(state.advance_iteration(), 1)
        self.assertFalse(state.is_exhausted)
        self.assertEqual(state.advance_iteration(), 2)
        self.assertTrue(state.is_exhausted)
        with self.assertRaisesRegex(RuntimeError, "iteration limit"):
            state.advance_iteration()

    def test_rejects_invalid_iteration_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            AgentState(max_iterations=0)
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            AgentState(iteration=3, max_iterations=2)
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            AgentState(iteration=True)


class AgentResultTests(unittest.TestCase):
    def test_factories_express_and_serialize_each_terminal_outcome(self) -> None:
        final_message = Message(role=MessageRole.ASSISTANT, content="Fix completed.")
        results = [
            AgentResult.succeeded(final_message=final_message, iterations=2),
            AgentResult.failed(error="provider unavailable", iterations=0),
            AgentResult.exhausted(iterations=3),
        ]

        self.assertEqual(results[0].status, AgentResultStatus.SUCCEEDED)
        self.assertEqual(results[1].status, AgentResultStatus.FAILED)
        self.assertEqual(results[2].status, AgentResultStatus.EXHAUSTED)
        for result in results:
            with self.subTest(status=result.status):
                self.assertEqual(AgentResult.from_dict(result.to_dict()), result)

    def test_success_requires_plain_final_assistant_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "final assistant text"):
            AgentResult.succeeded(
                final_message=Message(role=MessageRole.USER, content="not final"),
                iterations=1,
            )
        with self.assertRaisesRegex(ValueError, "final assistant text"):
            AgentResult.succeeded(final_message=assistant_call(), iterations=1)

    def test_failure_requires_error_and_exhaustion_is_distinct(self) -> None:
        with self.assertRaisesRegex(ValueError, "failed AgentResult.error"):
            AgentResult(status=AgentResultStatus.FAILED, iterations=1)
        with self.assertRaisesRegex(ValueError, "must not contain an error"):
            AgentResult(
                status=AgentResultStatus.EXHAUSTED,
                iterations=1,
                error="not a runtime failure",
            )
        with self.assertRaisesRegex(ValueError, "at least one iteration"):
            AgentResult.exhausted(iterations=0)


if __name__ == "__main__":
    unittest.main()
