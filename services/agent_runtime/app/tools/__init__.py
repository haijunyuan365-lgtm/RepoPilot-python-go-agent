"""Tool contracts for the RepoPilot agent runtime."""

# Registry 是其他 Tool 模块的底层契约，必须先完成初始化，避免
# app.agent.loop 反向导入 app.tools 时出现循环导入的半初始化状态。
from .registry import (
    DuplicateToolError,
    Tool,
    ToolHandler,
    ToolRegistry,
    ToolRegistryError,
    UnknownToolError,
)
from .apply_patch import ApplyPatchTool, build_apply_patch_tool
from .run_test import RunTestTool, TestExecutionError, build_run_test_tool
from .search_code import SearchCodeTool, build_search_code_tool
from .safe_read import (
    RepositoryAccessError,
    RepositoryBoundary,
    SafeReadTools,
    build_safe_read_tools,
)

__all__ = [
    "ApplyPatchTool",
    "DuplicateToolError",
    "RepositoryAccessError",
    "RepositoryBoundary",
    "RunTestTool",
    "SafeReadTools",
    "SearchCodeTool",
    "TestExecutionError",
    "Tool",
    "ToolHandler",
    "ToolRegistry",
    "ToolRegistryError",
    "UnknownToolError",
    "build_apply_patch_tool",
    "build_run_test_tool",
    "build_search_code_tool",
    "build_safe_read_tools",
]
