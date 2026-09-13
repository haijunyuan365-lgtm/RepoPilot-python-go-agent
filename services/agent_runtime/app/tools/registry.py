"""Provider-neutral tool definitions and registry lookup for RepoPilot."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agent.models import ToolCall, ToolResult


ToolHandler = Callable[["ToolCall"], "ToolResult"]


class ToolRegistryError(Exception):
    """Base error for deterministic tool registry failures."""


class DuplicateToolError(ToolRegistryError):
    """Raised when registration would silently replace an existing tool."""


class UnknownToolError(ToolRegistryError):
    """Raised when a requested tool name is not registered."""


def _require_non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _copy_json(value: Any, path: str) -> Any:
    """Validate and detach one JSON-compatible value."""

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


@dataclass(frozen=True, init=False)
class Tool:
    """A model-visible tool contract paired with its runtime handler.

    ``input_schema`` is stored as a defensive JSON-compatible snapshot. This
    step validates only the transport boundary and the required top-level
    object shape; semantic JSON Schema validation belongs with invocation in a
    later step.
    """

    name: str
    description: str
    _input_schema: dict[str, Any] = field(repr=False)
    handler: ToolHandler = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_schema: Mapping[str, Any],
        handler: ToolHandler,
    ) -> None:
        _require_non_empty(name, "Tool.name")
        _require_non_empty(description, "Tool.description")
        if not isinstance(input_schema, Mapping):
            raise ValueError("Tool.input_schema must be an object")
        schema = _copy_json(input_schema, "Tool.input_schema")
        if schema.get("type") != "object":
            raise ValueError("Tool.input_schema.type must be 'object'")
        if not callable(handler):
            raise ValueError("Tool.handler must be callable")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "_input_schema", schema)
        object.__setattr__(self, "handler", handler)

    @property
    def input_schema(self) -> dict[str, Any]:
        """Return a detached schema so callers cannot mutate the contract."""

        return deepcopy(self._input_schema)

    def to_dict(self) -> dict[str, Any]:
        """Return the provider-neutral model-facing definition."""

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Register tools once and resolve them by their exact model-facing name."""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise ValueError("tool must be a Tool")
        if tool.name in self._tools:
            raise DuplicateToolError(f"tool is already registered: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        _require_non_empty(name, "tool name")
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(f"unknown tool: {name!r}") from None

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered names in deterministic registration order."""

        return tuple(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        """Return detached model-facing definitions in registration order."""

        return [tool.to_dict() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
