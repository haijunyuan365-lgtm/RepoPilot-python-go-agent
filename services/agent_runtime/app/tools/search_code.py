"""Repository-bounded exact text search for the Phase 1 runtime."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter_ns

from app.agent.models import ToolCall, ToolResult

from .registry import Tool
from .safe_read import RepositoryAccessError, RepositoryBoundary


DEFAULT_MAX_MATCHES = 100
DEFAULT_MAX_OUTPUT_CHARS = 100_000
DEFAULT_MAX_SCANNED_FILES = 5_000
DEFAULT_MAX_SCANNED_ENTRIES = 20_000
DEFAULT_MAX_FILE_CHARS = 100_000


class SearchCodeTool:
    """Build and execute one exact-text ``search_code`` tool."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        max_matches: int = DEFAULT_MAX_MATCHES,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        max_scanned_files: int = DEFAULT_MAX_SCANNED_FILES,
        max_scanned_entries: int = DEFAULT_MAX_SCANNED_ENTRIES,
        max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
    ) -> None:
        self._require_positive_int(max_matches, "max_matches")
        self._require_positive_int(max_output_chars, "max_output_chars")
        self._require_positive_int(max_scanned_files, "max_scanned_files")
        self._require_positive_int(max_scanned_entries, "max_scanned_entries")
        self._require_positive_int(max_file_chars, "max_file_chars")
        if max_output_chars < 2:
            raise ValueError("max_output_chars must allow at least an empty JSON array")

        self._boundary = RepositoryBoundary(repository_root)
        self._max_matches = max_matches
        self._max_output_chars = max_output_chars
        self._max_scanned_files = max_scanned_files
        self._max_scanned_entries = max_scanned_entries
        self._max_file_chars = max_file_chars

    @staticmethod
    def _require_positive_int(value: object, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    def definition(self) -> Tool:
        """Return the model-visible Tool definition bound to this repository."""

        return Tool(
            name="search_code",
            description=(
                "Search UTF-8 repository text for a case-sensitive literal query "
                "and return JSON matches with path, line, column, and text."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "path": {"type": "string", "default": "."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=self.search_code,
        )

    def search_code(self, call: ToolCall) -> ToolResult:
        """Search one verified file or directory and return bounded JSON hits."""

        started = perf_counter_ns()
        try:
            query, relative_path = self._arguments(call)
            target = self._boundary.resolve(relative_path)
            single_file_search = target.is_file()
            candidates, truncated = self._collect_candidate_files(target)
            matches: list[dict[str, object]] = []

            for relative_name, file_path in candidates:
                try:
                    content, file_truncated = self._read_text(file_path)
                except (RepositoryAccessError, OSError):
                    # 搜索目录时，二进制、失效或不可读文件不应让其他文本文件
                    # 的命中全部丢失；显式搜索单个文件时则返回真实失败。
                    if single_file_search:
                        raise
                    continue

                truncated = truncated or file_truncated
                for line_number, line in enumerate(content.splitlines(), start=1):
                    column = line.find(query)
                    if column < 0:
                        continue
                    hit = {
                        "path": relative_name,
                        "line": line_number,
                        "column": column + 1,
                        "text": line,
                    }

                    # 始终对完整结果重新编码后再判断上限，避免直接截断字符串
                    # 产生无法解析的半段 JSON。
                    if len(matches) >= self._max_matches:
                        truncated = True
                        break
                    encoded_with_hit = self._encode_matches([*matches, hit])
                    if len(encoded_with_hit) > self._max_output_chars:
                        truncated = True
                        break
                    matches.append(hit)
                else:
                    continue
                break

            return self._success(
                call,
                self._encode_matches(matches),
                started,
                truncated=truncated,
            )
        except (RepositoryAccessError, OSError) as exc:
            return self._failure(call, str(exc), started)

    def _collect_candidate_files(self, target: Path) -> tuple[list[tuple[str, Path]], bool]:
        if target.is_file():
            return [(self._boundary.relative_name(target), target)], False
        if not target.is_dir():
            raise RepositoryAccessError("search_code path must be a file or directory")

        candidates: dict[str, Path] = {}
        pending = [target]
        visited_directories: set[Path] = set()
        scanned_entries = 0
        truncated = False

        while pending:
            current = pending.pop()
            if current in visited_directories:
                continue
            visited_directories.add(current)

            # 与 Safe Read 一样，必须先解析真实路径再纳入搜索范围；这样既
            # 跳过越界链接，也能通过 visited 集合阻止目录链接环。
            children = sorted(current.iterdir(), key=lambda path: path.name.casefold())
            for child in children:
                scanned_entries += 1
                if scanned_entries > self._max_scanned_entries:
                    truncated = True
                    pending.clear()
                    break
                try:
                    resolved = child.resolve(strict=True)
                    relative_name = self._boundary.relative_name(resolved)
                except (FileNotFoundError, OSError, RuntimeError, RepositoryAccessError):
                    continue

                if resolved.is_dir():
                    pending.append(resolved)
                elif resolved.is_file():
                    candidates[relative_name] = resolved
                    if len(candidates) > self._max_scanned_files:
                        truncated = True
                        pending.clear()
                        break

        ordered = sorted(candidates.items())
        return ordered[: self._max_scanned_files], truncated

    def _read_text(self, file_path: Path) -> tuple[str, bool]:
        try:
            # 每个文件只读取上限再多一个字符，用固定内存开销判断搜索范围
            # 是否完整；超出范围通过 ToolResult.truncated 显式反馈。
            with file_path.open("r", encoding="utf-8", errors="strict", newline="") as stream:
                content = stream.read(self._max_file_chars + 1)
        except UnicodeError as exc:
            raise RepositoryAccessError("file is not valid UTF-8 text") from exc

        if "\x00" in content:
            raise RepositoryAccessError(
                "file contains null bytes and is not treated as text"
            )
        truncated = len(content) > self._max_file_chars
        return content[: self._max_file_chars], truncated

    @staticmethod
    def _arguments(call: ToolCall) -> tuple[str, str]:
        unexpected = sorted(set(call.arguments) - {"query", "path"})
        if unexpected:
            raise RepositoryAccessError(
                f"unexpected tool arguments: {', '.join(unexpected)}"
            )

        query = call.arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise RepositoryAccessError("query argument must be a non-empty string")
        if "\n" in query or "\r" in query:
            raise RepositoryAccessError("query argument must be a single line")

        relative_path = call.arguments.get("path", ".")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise RepositoryAccessError("path argument must be a non-empty string")
        return query, relative_path

    @staticmethod
    def _encode_matches(matches: list[dict[str, object]]) -> str:
        return json.dumps(matches, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _elapsed_ms(started: int) -> int:
        return max(0, (perf_counter_ns() - started) // 1_000_000)

    def _success(
        self,
        call: ToolCall,
        output: str,
        started: int,
        *,
        truncated: bool,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            success=True,
            output=output,
            duration_ms=self._elapsed_ms(started),
            truncated=truncated,
        )

    def _failure(self, call: ToolCall, error: str, started: int) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            success=False,
            error=error,
            duration_ms=self._elapsed_ms(started),
        )


def build_search_code_tool(
    repository_root: str | Path,
    *,
    max_matches: int = DEFAULT_MAX_MATCHES,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    max_scanned_files: int = DEFAULT_MAX_SCANNED_FILES,
    max_scanned_entries: int = DEFAULT_MAX_SCANNED_ENTRIES,
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
) -> Tool:
    """Build the Phase 1.5 search tool for one fixed repository root."""

    return SearchCodeTool(
        repository_root,
        max_matches=max_matches,
        max_output_chars=max_output_chars,
        max_scanned_files=max_scanned_files,
        max_scanned_entries=max_scanned_entries,
        max_file_chars=max_file_chars,
    ).definition()
