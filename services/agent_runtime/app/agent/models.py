"""Provider-neutral data models for the RepoPilot agent runtime.

This module deliberately contains data and invariants only. Tool lookup,
execution, provider conversion, and the agent loop belong to later Phase 1
steps.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    """Roles understood by RepoPilot's internal conversation model."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentResultStatus(str, Enum):
    """Terminal ouxtcomes produced by a future agent loop."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


def _require_non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _copy_json(value: Any, path: str = "arguments") -> Any:
    """Validate and detach a JSON-compatible value.

    Tool arguments cross process and provider boundaries later in the project,
    so accepting arbitrary Python objects here would make serialization fail at
    a less useful point.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or infinity")
        return value
    if isinstance(value, list):
        return [_copy_json(item, f"{path}[]") for item in value]
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            copied[key] = _copy_json(item, f"{path}.{key}")
        return copied
    raise ValueError(f"{path} contains a non-JSON value: {type(value).__name__}")


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


@dataclass(frozen=True)
class ToolCall:
    """One model request to invoke a named tool with JSON arguments."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.id, "ToolCall.id")
        _require_non_empty(self.name, "ToolCall.name")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("ToolCall.arguments must be an object")
        object.__setattr__(self, "arguments", _copy_json(self.arguments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": deepcopy(self.arguments),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ToolCall":
        values = _require_mapping(data, "ToolCall")
        return cls(
            id=values.get("id"),
            name=values.get("name"),
            arguments=values.get("arguments", {}),
        )


@dataclass(frozen=True)
class ToolResult:
    """The structured observation for exactly one ToolCall."""

    tool_call_id: str
    tool_name: str
    success: bool
    output: str = ""
    error: str | None = None
    duration_ms: int = 0
    truncated: bool = False

    def __post_init__(self) -> None:
        _require_non_empty(self.tool_call_id, "ToolResult.tool_call_id")
        _require_non_empty(self.tool_name, "ToolResult.tool_name")
        if not isinstance(self.success, bool):
            raise ValueError("ToolResult.success must be a boolean")
        if not isinstance(self.output, str):
            raise ValueError("ToolResult.output must be a string")
        _require_non_negative_int(self.duration_ms, "ToolResult.duration_ms")
        if not isinstance(self.truncated, bool):
            raise ValueError("ToolResult.truncated must be a boolean")

        if self.success:
            if self.error is not None:
                raise ValueError("a successful ToolResult must not contain an error")
        else:
            _require_non_empty(self.error, "a failed ToolResult.error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ToolResult":
        values = _require_mapping(data, "ToolResult")
        return cls(
            tool_call_id=values.get("tool_call_id"),
            tool_name=values.get("tool_name"),
            success=values.get("success"),
            output=values.get("output", ""),
            error=values.get("error"),
            duration_ms=values.get("duration_ms", 0),
            truncated=values.get("truncated", False),
        )


@dataclass(frozen=True)
class Message:
    """One provider-neutral conversation item.

    System and user messages contain text. Assistant messages contain text,
    tool calls, or both. Tool messages contain one structured ToolResult.
    """

    role: MessageRole
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_result: ToolResult | None = None

    def __post_init__(self) -> None:
        try:
            role = MessageRole(self.role)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported Message.role: {self.role!r}") from exc
        object.__setattr__(self, "role", role)

        if not isinstance(self.content, str):
            raise ValueError("Message.content must be a string")
        calls = tuple(self.tool_calls)
        if any(not isinstance(call, ToolCall) for call in calls):
            raise ValueError("Message.tool_calls must contain only ToolCall values")
        object.__setattr__(self, "tool_calls", calls)

        if role is MessageRole.TOOL:
            if self.tool_result is None:
                raise ValueError("a tool Message requires tool_result")
            if self.content or calls:
                raise ValueError("a tool Message cannot contain content or tool_calls")
            return

        if self.tool_result is not None:
            raise ValueError("only a tool Message may contain tool_result")
        if calls and role is not MessageRole.ASSISTANT:
            raise ValueError("only an assistant Message may contain tool_calls")
        if role in (MessageRole.SYSTEM, MessageRole.USER) and not self.content.strip():
            raise ValueError(f"a {role.value} Message requires content")
        if role is MessageRole.ASSISTANT and not self.content.strip() and not calls:
            raise ValueError("an assistant Message requires content or tool_calls")

        call_ids = [call.id for call in calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("Message.tool_calls contains duplicate ids")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "content": self.content,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "tool_result": self.tool_result.to_dict() if self.tool_result else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Message":
        values = _require_mapping(data, "Message")
        raw_calls = values.get("tool_calls", [])
        if not isinstance(raw_calls, list):
            raise ValueError("Message.tool_calls must be an array")
        raw_result = values.get("tool_result")
        return cls(
            role=values.get("role"),
            content=values.get("content", ""),
            tool_calls=tuple(ToolCall.from_dict(call) for call in raw_calls),
            tool_result=(ToolResult.from_dict(raw_result) if raw_result is not None else None),
        )


@dataclass
class AgentState:
    """Mutable working state owned by one future agent-loop invocation."""

    messages: list[Message] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 10

    def __post_init__(self) -> None:
        self.messages = list(self.messages)
        if any(not isinstance(message, Message) for message in self.messages):
            raise ValueError("AgentState.messages must contain only Message values")
        _require_non_negative_int(self.iteration, "AgentState.iteration")
        if (
            isinstance(self.max_iterations, bool)
            or not isinstance(self.max_iterations, int)
            or self.max_iterations <= 0
        ):
            raise ValueError("AgentState.max_iterations must be a positive integer")
        if self.iteration > self.max_iterations:
            raise ValueError("AgentState.iteration cannot exceed max_iterations")
        self._validate_transcript(self.messages)

    @staticmethod
    def _pending_calls(messages: list[Message]) -> dict[str, ToolCall]:
        seen_ids: set[str] = set()
        pending: dict[str, ToolCall] = {}

        for message in messages:
            for call in message.tool_calls:
                if call.id in seen_ids:
                    raise ValueError(f"duplicate tool call id in AgentState: {call.id}")
                seen_ids.add(call.id)
                pending[call.id] = call

            if message.tool_result is None:
                continue
            result = message.tool_result
            call = pending.get(result.tool_call_id)
            if call is None:
                raise ValueError(
                    "ToolResult must reference an earlier unresolved ToolCall: "
                    f"{result.tool_call_id}"
                )
            if call.name != result.tool_name:
                raise ValueError(
                    "ToolResult.tool_name does not match its ToolCall: "
                    f"expected {call.name!r}, got {result.tool_name!r}"
                )
            del pending[result.tool_call_id]

        return pending

    @classmethod
    def _validate_transcript(cls, messages: list[Message]) -> None:
        cls._pending_calls(messages)

    @property
    def pending_tool_calls(self) -> tuple[ToolCall, ...]:
        """Return calls that do not yet have a ToolResult, in insertion order."""

        return tuple(self._pending_calls(self.messages).values())

    @property
    def is_exhausted(self) -> bool:
        return self.iteration >= self.max_iterations

    def append_message(self, message: Message) -> None:
        if not isinstance(message, Message):
            raise ValueError("message must be a Message")
        candidate = [*self.messages, message]
        self._validate_transcript(candidate)
        self.messages.append(message)

    def advance_iteration(self) -> int:
        """Enter one loop iteration without exceeding the configured budget."""

        if self.is_exhausted:
            raise RuntimeError("agent iteration limit is exhausted")
        self.iteration += 1
        return self.iteration

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": [message.to_dict() for message in self.messages],
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentState":
        values = _require_mapping(data, "AgentState")
        raw_messages = values.get("messages", [])
        if not isinstance(raw_messages, list):
            raise ValueError("AgentState.messages must be an array")
        return cls(
            messages=[Message.from_dict(message) for message in raw_messages],
            iteration=values.get("iteration", 0),
            max_iterations=values.get("max_iterations", 10),
        )


@dataclass(frozen=True)
class AgentResult:
    """One explicit terminal outcome of a future agent-loop invocation."""

    status: AgentResultStatus
    iterations: int
    final_message: Message | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        try:
            status = AgentResultStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported AgentResult.status: {self.status!r}") from exc
        object.__setattr__(self, "status", status)
        _require_non_negative_int(self.iterations, "AgentResult.iterations")

        if status is AgentResultStatus.SUCCEEDED:
            if self.final_message is None:
                raise ValueError("a succeeded AgentResult requires final_message")
            if (
                self.final_message.role is not MessageRole.ASSISTANT
                or not self.final_message.content.strip()
                or self.final_message.tool_calls
            ):
                raise ValueError(
                    "a succeeded AgentResult requires a final assistant text Message"
                )
            if self.error is not None:
                raise ValueError("a succeeded AgentResult must not contain an error")
            return

        if self.final_message is not None:
            raise ValueError("a non-success AgentResult must not contain final_message")
        if status is AgentResultStatus.FAILED:
            _require_non_empty(self.error, "a failed AgentResult.error")
        elif self.error is not None:
            raise ValueError("an exhausted AgentResult must not contain an error")
        if status is AgentResultStatus.EXHAUSTED and self.iterations == 0:
            raise ValueError("an exhausted AgentResult requires at least one iteration")

    @classmethod
    def succeeded(cls, final_message: Message, iterations: int) -> "AgentResult":
        return cls(
            status=AgentResultStatus.SUCCEEDED,
            iterations=iterations,
            final_message=final_message,
        )

    @classmethod
    def failed(cls, error: str, iterations: int) -> "AgentResult":
        return cls(
            status=AgentResultStatus.FAILED,
            iterations=iterations,
            error=error,
        )

    @classmethod
    def exhausted(cls, iterations: int) -> "AgentResult":
        return cls(status=AgentResultStatus.EXHAUSTED, iterations=iterations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "iterations": self.iterations,
            "final_message": (
                self.final_message.to_dict() if self.final_message is not None else None
            ),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentResult":
        values = _require_mapping(data, "AgentResult")
        raw_message = values.get("final_message")
        return cls(
            status=values.get("status"),
            iterations=values.get("iterations"),
            final_message=(Message.from_dict(raw_message) if raw_message is not None else None),
            error=values.get("error"),
        )
