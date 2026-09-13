"""Repository-bounded unified-diff application for the Phase 1 runtime."""

from __future__ import annotations

import difflib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns

from app.agent.models import ToolCall, ToolResult

from .registry import Tool
from .safe_read import RepositoryAccessError, RepositoryBoundary


DEFAULT_MAX_PATCH_CHARS = 200_000
DEFAULT_MAX_FILE_CHARS = 500_000
DEFAULT_MAX_OUTPUT_CHARS = 200_000

_HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$"
)
_NO_NEWLINE_MARKER = r"\ No newline at end of file"


class PatchError(Exception):
    """Raised when a patch is malformed, conflicts, or is outside this step's scope."""


@dataclass(frozen=True)
class _TextLine:
    content: str
    ending: str

    @property
    def has_newline(self) -> bool:
        return bool(self.ending)


@dataclass(frozen=True)
class _PatchLine:
    kind: str
    content: str
    has_newline: bool = True


@dataclass(frozen=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[_PatchLine, ...]


@dataclass(frozen=True)
class _ParsedPatch:
    path: str
    hunks: tuple[_Hunk, ...]


class ApplyPatchTool:
    """Build and execute one repository-bounded ``apply_patch`` tool."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        max_patch_chars: int = DEFAULT_MAX_PATCH_CHARS,
        max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        self._require_positive_int(max_patch_chars, "max_patch_chars")
        self._require_positive_int(max_file_chars, "max_file_chars")
        self._require_positive_int(max_output_chars, "max_output_chars")
        self._boundary = RepositoryBoundary(repository_root)
        self._max_patch_chars = max_patch_chars
        self._max_file_chars = max_file_chars
        self._max_output_chars = max_output_chars

    @staticmethod
    def _require_positive_int(value: object, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    def definition(self) -> Tool:
        """Return the model-visible Tool definition bound to this repository."""

        return Tool(
            name="apply_patch",
            description=(
                "Apply one unified diff to one existing UTF-8 repository file. "
                "Use --- a/path and +++ b/path headers; file creation, deletion, "
                "rename, and multi-file patches are not supported."
            ),
            input_schema={
                "type": "object",
                "properties": {"patch": {"type": "string", "minLength": 1}},
                "required": ["patch"],
                "additionalProperties": False,
            },
            handler=self.apply_patch,
        )

    def apply_patch(self, call: ToolCall) -> ToolResult:
        """Validate and atomically apply one unified diff to an existing text file."""

        started = perf_counter_ns()
        try:
            patch_text = self._patch_argument(call)
            parsed = self._parse_patch(patch_text)
            file_path = self._resolve_direct_file(parsed.path)
            original = self._read_text(file_path)
            original_lines = self._split_text_lines(original)
            updated_lines = self._apply_hunks(original_lines, parsed.hunks)
            updated = self._join_text_lines(updated_lines)
            if updated == original:
                raise PatchError("patch does not change the target file")

            diff = self._render_unified_diff(
                original_lines,
                updated_lines,
                parsed.path,
            )
            # 所有语法、路径、上下文和范围检查都完成后才写盘；因此无效
            # hunk 或冲突不会留下“只应用了一半”的文件状态。
            self._atomic_write(file_path, updated)
            truncated = len(diff) > self._max_output_chars
            return self._success(
                call,
                diff[: self._max_output_chars],
                started,
                truncated=truncated,
            )
        except UnicodeError:
            return self._failure(call, "file is not valid UTF-8 text", started)
        except (PatchError, RepositoryAccessError, OSError) as exc:
            return self._failure(call, str(exc), started)

    def _patch_argument(self, call: ToolCall) -> str:
        unexpected = sorted(set(call.arguments) - {"patch"})
        if unexpected:
            raise PatchError(f"unexpected tool arguments: {', '.join(unexpected)}")
        patch_text = call.arguments.get("patch")
        if not isinstance(patch_text, str) or not patch_text.strip():
            raise PatchError("patch argument must be a non-empty string")
        if "\x00" in patch_text:
            raise PatchError("patch argument must not contain null bytes")
        if len(patch_text) > self._max_patch_chars:
            raise PatchError(
                f"patch exceeds the {self._max_patch_chars} character limit"
            )
        return patch_text

    def _parse_patch(self, patch_text: str) -> _ParsedPatch:
        raw_lines = patch_text.splitlines(keepends=True)
        if len(raw_lines) < 3:
            raise PatchError("patch must contain file headers and at least one hunk")

        old_path = self._parse_file_header(raw_lines[0], "--- ", "a/")
        new_path = self._parse_file_header(raw_lines[1], "+++ ", "b/")
        if old_path != new_path:
            raise PatchError("patch old and new paths must identify the same file")

        hunks: list[_Hunk] = []
        has_change = False
        index = 2
        while index < len(raw_lines):
            header = self._strip_line_ending(raw_lines[index])
            if header.startswith(("--- ", "+++ ")):
                raise PatchError("multi-file patches are not supported")
            match = _HUNK_HEADER.fullmatch(header)
            if match is None:
                raise PatchError(f"invalid hunk header: {header!r}")

            old_start, old_count, new_start, new_count = self._parse_hunk_range(match)
            self._validate_hunk_start(old_start, old_count, "old")
            self._validate_hunk_start(new_start, new_count, "new")
            index += 1
            body: list[_PatchLine] = []
            old_seen = 0
            new_seen = 0

            # hunk 声明的行数是结构契约。严格按计数消费正文，既能识别
            # 截断 Patch，也能避免把下一段 header 错当成普通删除行。
            while old_seen < old_count or new_seen < new_count:
                if index >= len(raw_lines):
                    raise PatchError("hunk body does not match its declared line counts")
                logical = self._strip_line_ending(raw_lines[index])
                if logical == _NO_NEWLINE_MARKER:
                    self._mark_previous_without_newline(body)
                    index += 1
                    continue
                if not self._has_line_ending(raw_lines[index]):
                    raise PatchError(
                        "patch body lines must end with a line break; use the "
                        "no-newline marker for an unterminated file line"
                    )
                if not logical or logical[0] not in {" ", "+", "-"}:
                    raise PatchError(f"invalid hunk body line: {logical!r}")

                kind = logical[0]
                body.append(_PatchLine(kind=kind, content=logical[1:]))
                if kind in {" ", "-"}:
                    old_seen += 1
                if kind in {" ", "+"}:
                    new_seen += 1
                if old_seen > old_count or new_seen > new_count:
                    raise PatchError("hunk body exceeds its declared line counts")
                if kind in {"+", "-"}:
                    has_change = True
                index += 1

            if index < len(raw_lines):
                logical = self._strip_line_ending(raw_lines[index])
                if logical == _NO_NEWLINE_MARKER:
                    self._mark_previous_without_newline(body)
                    index += 1

            if old_seen != old_count or new_seen != new_count:
                raise PatchError("hunk body does not match its declared line counts")
            hunks.append(
                _Hunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=tuple(body),
                )
            )

        if not hunks:
            raise PatchError("patch must contain at least one hunk")
        if not has_change:
            raise PatchError("patch must contain at least one added or removed line")
        return _ParsedPatch(path=old_path, hunks=tuple(hunks))

    @staticmethod
    def _parse_file_header(raw_line: str, marker: str, path_prefix: str) -> str:
        header = ApplyPatchTool._strip_line_ending(raw_line)
        if not header.startswith(marker):
            raise PatchError(f"patch must start with {marker.strip()!r} file header")
        raw_path = header[len(marker) :]
        if "\t" in raw_path:
            raise PatchError("file header timestamps are not supported")
        if raw_path == "/dev/null":
            raise PatchError("file creation and deletion are not supported")
        if not raw_path.startswith(path_prefix) or len(raw_path) == len(path_prefix):
            raise PatchError(f"file header path must start with {path_prefix!r}")
        return raw_path[len(path_prefix) :]

    @staticmethod
    def _parse_hunk_range(match: re.Match[str]) -> tuple[int, int, int, int]:
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) is not None else 1
        return old_start, old_count, new_start, new_count

    @staticmethod
    def _validate_hunk_start(start: int, count: int, label: str) -> None:
        if count > 0 and start == 0:
            raise PatchError(f"{label} hunk start must be at least 1 for non-empty ranges")

    @staticmethod
    def _mark_previous_without_newline(body: list[_PatchLine]) -> None:
        if not body or not body[-1].has_newline:
            raise PatchError("no-newline marker must follow one hunk body line")
        previous = body[-1]
        body[-1] = _PatchLine(
            kind=previous.kind,
            content=previous.content,
            has_newline=False,
        )

    def _resolve_direct_file(self, relative_path: str) -> Path:
        file_path = self._boundary.resolve(relative_path)
        if not file_path.is_file():
            raise RepositoryAccessError("apply_patch path must be a regular file")

        # 读取工具可以安全地跟随仓库内链接；写入工具更严格，拒绝通过
        # symlink/Junction 别名修改另一个位置，确保 Patch 路径就是落盘目标。
        lexical_path = Path(os.path.abspath(self._boundary.root / Path(relative_path)))
        if os.path.normcase(str(lexical_path)) != os.path.normcase(str(file_path)):
            raise RepositoryAccessError(
                "apply_patch does not write through symbolic links or junctions"
            )
        return file_path

    def _read_text(self, file_path: Path) -> str:
        with file_path.open("r", encoding="utf-8", errors="strict", newline="") as stream:
            content = stream.read(self._max_file_chars + 1)
        if len(content) > self._max_file_chars:
            raise PatchError(f"target file exceeds the {self._max_file_chars} character limit")
        if "\x00" in content:
            raise RepositoryAccessError(
                "file contains null bytes and is not treated as text"
            )
        return content

    def _apply_hunks(
        self,
        source: list[_TextLine],
        hunks: tuple[_Hunk, ...],
    ) -> list[_TextLine]:
        preferred_ending = next((line.ending for line in source if line.ending), "\n")
        result: list[_TextLine] = []
        source_cursor = 0

        for hunk in hunks:
            source_start = (
                hunk.old_start if hunk.old_count == 0 else hunk.old_start - 1
            )
            if source_start < source_cursor:
                raise PatchError("patch hunks overlap or are out of order")
            if source_start > len(source):
                raise PatchError("patch hunk starts beyond the end of the target file")
            result.extend(source[source_cursor:source_start])

            expected_new_start = (
                hunk.new_start if hunk.new_count == 0 else hunk.new_start - 1
            )
            if expected_new_start != len(result):
                raise PatchError("patch new hunk range does not align with prior changes")

            current = source_start
            for patch_line in hunk.lines:
                if patch_line.kind in {" ", "-"}:
                    if current >= len(source) or not self._line_matches(
                        source[current], patch_line
                    ):
                        raise PatchError(
                            f"patch conflict at source line {current + 1}: "
                            "context or removed text does not match"
                        )
                    if patch_line.kind == " ":
                        result.append(source[current])
                    current += 1
                elif patch_line.kind == "+":
                    result.append(
                        _TextLine(
                            content=patch_line.content,
                            ending=preferred_ending if patch_line.has_newline else "",
                        )
                    )
            source_cursor = current

        result.extend(source[source_cursor:])
        return result

    @staticmethod
    def _line_matches(source: _TextLine, patch_line: _PatchLine) -> bool:
        return (
            source.content == patch_line.content
            and source.has_newline == patch_line.has_newline
        )

    @staticmethod
    def _split_text_lines(content: str) -> list[_TextLine]:
        lines: list[_TextLine] = []
        for raw_line in content.splitlines(keepends=True):
            ending = ""
            if raw_line.endswith("\r\n"):
                ending = "\r\n"
            elif raw_line.endswith("\n"):
                ending = "\n"
            elif raw_line.endswith("\r"):
                ending = "\r"
            lines.append(
                _TextLine(
                    content=raw_line[: -len(ending)] if ending else raw_line,
                    ending=ending,
                )
            )
        return lines

    @staticmethod
    def _join_text_lines(lines: list[_TextLine]) -> str:
        return "".join(f"{line.content}{line.ending}" for line in lines)

    @staticmethod
    def _render_unified_diff(
        before: list[_TextLine],
        after: list[_TextLine],
        relative_path: str,
    ) -> str:
        before_keys = [(line.content, line.has_newline) for line in before]
        after_keys = [(line.content, line.has_newline) for line in after]
        matcher = difflib.SequenceMatcher(
            None,
            before_keys,
            after_keys,
            autojunk=False,
        )
        output = [f"--- a/{relative_path}\n", f"+++ b/{relative_path}\n"]
        for group in matcher.get_grouped_opcodes(n=3):
            first, last = group[0], group[-1]
            old_range = ApplyPatchTool._format_unified_range(first[1], last[2])
            new_range = ApplyPatchTool._format_unified_range(first[3], last[4])
            output.append(f"@@ -{old_range} +{new_range} @@\n")
            for tag, old_start, old_end, new_start, new_end in group:
                if tag == "equal":
                    for line in before[old_start:old_end]:
                        ApplyPatchTool._append_diff_line(output, " ", line)
                elif tag in {"delete", "replace"}:
                    for line in before[old_start:old_end]:
                        ApplyPatchTool._append_diff_line(output, "-", line)
                if tag in {"insert", "replace"}:
                    for line in after[new_start:new_end]:
                        ApplyPatchTool._append_diff_line(output, "+", line)
        return "".join(output)

    @staticmethod
    def _format_unified_range(start: int, stop: int) -> str:
        beginning = start + 1
        length = stop - start
        if length == 1:
            return str(beginning)
        if length == 0:
            beginning -= 1
        return f"{beginning},{length}"

    @staticmethod
    def _append_diff_line(output: list[str], prefix: str, line: _TextLine) -> None:
        output.append(f"{prefix}{line.content}\n")
        if not line.has_newline:
            output.append(f"{_NO_NEWLINE_MARKER}\n")

    @staticmethod
    def _atomic_write(file_path: Path, content: str) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".repopilot-patch-",
            suffix=".tmp",
            dir=file_path.parent,
        )
        temporary_path = Path(temporary_name)
        descriptor_open = True
        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                errors="strict",
                newline="",
            ) as stream:
                descriptor_open = False
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, stat.S_IMODE(file_path.stat().st_mode))
            # 临时文件与目标位于同一目录，os.replace 不会暴露部分写入内容。
            os.replace(temporary_path, file_path)
        finally:
            if descriptor_open:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _strip_line_ending(line: str) -> str:
        if line.endswith("\r\n"):
            return line[:-2]
        if line.endswith(("\n", "\r")):
            return line[:-1]
        return line

    @staticmethod
    def _has_line_ending(line: str) -> bool:
        return line.endswith(("\n", "\r"))

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


def build_apply_patch_tool(
    repository_root: str | Path,
    *,
    max_patch_chars: int = DEFAULT_MAX_PATCH_CHARS,
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> Tool:
    """Build the Phase 1.6 patch tool for one fixed repository root."""

    return ApplyPatchTool(
        repository_root,
        max_patch_chars=max_patch_chars,
        max_file_chars=max_file_chars,
        max_output_chars=max_output_chars,
    ).definition()
