"""Transparent, provider-neutral agent loop for the Phase 1 runtime."""

from __future__ import annotations

from typing import Any, Protocol

from app.agent.models import (
    AgentResult,
    AgentState,
    Message,
    MessageRole,
    ToolCall,
    ToolResult,
)
from app.tools import ToolRegistry, UnknownToolError


class ChatModel(Protocol):
    """Minimal model boundary required by the agent loop.

    Provider adapters added in a later step will translate these internal
    messages and tool definitions to their SDK-specific request format.
    """

    def complete(
        self,
        messages: tuple[Message, ...],
        tools: list[dict[str, Any]],
    ) -> Message:
        """Return the next assistant message for the current transcript."""


class AgentLoop:
    """Run model turns and feed structured tool observations back to the model."""

    def __init__(self, *, model: ChatModel, tools: ToolRegistry) -> None:
        if not callable(getattr(model, "complete", None)):
            raise ValueError("model must provide a callable complete method")
        if not isinstance(tools, ToolRegistry):
            raise ValueError("tools must be a ToolRegistry")
        self._model = model
        self._tools = tools

    def run(self, state: AgentState) -> AgentResult:
        """Mutate ``state`` until a final answer, failure, or budget exhaustion."""

        if not isinstance(state, AgentState):
            raise ValueError("state must be an AgentState")
        if state.pending_tool_calls:
            return AgentResult.failed(
                error="agent state has unresolved tool calls before loop start",
                iterations=state.iteration,
            )

        while not state.is_exhausted:
            state.advance_iteration()
            response = self._complete(state)
            if isinstance(response, AgentResult):
                return response

            try:
                state.append_message(response)
            except ValueError as exc:
                return AgentResult.failed(
                    error=f"chat model returned an invalid assistant message: {exc}",
                    iterations=state.iteration,
                )

            if not response.tool_calls:
                return AgentResult.succeeded(
                    final_message=response,
                    iterations=state.iteration,
                )

            for call in response.tool_calls:
                result = self._execute_tool(call)
                state.append_message(
                    Message(role=MessageRole.TOOL, tool_result=result)
                )

        return AgentResult.exhausted(iterations=state.iteration)

    def _complete(self, state: AgentState) -> Message | AgentResult:
        try:
            response = self._model.complete(
                tuple(state.messages),
                self._tools.schemas(),
            )
        except Exception as exc:
            return AgentResult.failed(
                error=f"chat model failed: {type(exc).__name__}: {exc}",
                iterations=state.iteration,
            )

        if not isinstance(response, Message):
            return AgentResult.failed(
                error="chat model must return a Message",
                iterations=state.iteration,
            )
        if response.role is not MessageRole.ASSISTANT:
            return AgentResult.failed(
                error="chat model must return an assistant Message",
                iterations=state.iteration,
            )
        return response

    def _execute_tool(self, call: ToolCall) -> ToolResult:
        try:
            tool = self._tools.get(call.name)
        except UnknownToolError as exc:
            return self._failed_tool_result(call, str(exc))

        try:
            result = tool.handler(call)
        except Exception as exc:
            return self._failed_tool_result(
                call,
                f"tool handler failed: {type(exc).__name__}: {exc}",
            )

        if not isinstance(result, ToolResult):
            return self._failed_tool_result(
                call,
                "tool handler must return a ToolResult",
            )
        if result.tool_call_id != call.id or result.tool_name != call.name:
            return self._failed_tool_result(
                call,
                "tool handler returned a result for a different tool call",
            )
        return result

    @staticmethod
    def _failed_tool_result(call: ToolCall, error: str) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            success=False,
            error=error,
        )
