"""Tool contracts for the RepoPilot agent runtime."""

from .registry import (
    DuplicateToolError,
    Tool,
    ToolHandler,
    ToolRegistry,
    ToolRegistryError,
    UnknownToolError,
)
from .search_code import SearchCodeTool, build_search_code_tool
from .safe_read import (
    RepositoryAccessError,
    RepositoryBoundary,
    SafeReadTools,
    build_safe_read_tools,
)

__all__ = [
    "DuplicateToolError",
    "RepositoryAccessError",
    "RepositoryBoundary",
    "SafeReadTools",
    "SearchCodeTool",
    "Tool",
    "ToolHandler",
    "ToolRegistry",
    "ToolRegistryError",
    "UnknownToolError",
    "build_search_code_tool",
    "build_safe_read_tools",
]
