"""Repository-bounded read-only tools for the Phase 1 runtime."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from time import perf_counter_ns

from app.agent.models import ToolCall, ToolResult

from .registry import Tool


DEFAULT_MAX_FILE_CHARS = 100_000
DEFAULT_MAX_LIST_ENTRIES = 1_000
DEFAULT_MAX_SCANNED_ENTRIES = 20_000

_PROTECTED_NAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".ssh",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
    "service-account.json",
}
_PROTECTED_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
_SAFE_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")


class RepositoryAccessError(Exception):
    """Raised when a repository path is invalid, protected, or out of bounds."""


def _is_protected(parts: tuple[str, ...]) -> bool:
    for part in parts:
        lowered = part.casefold()
        if lowered == ".git" or lowered in _PROTECTED_NAMES:
            return True
        if lowered == ".env" or (
            lowered.startswith(".env.")
            and not lowered.endswith(_SAFE_ENV_TEMPLATE_SUFFIXES)
        ):
            return True
        if any(lowered.endswith(suffix) for suffix in _PROTECTED_SUFFIXES):
            return True
    return False


class RepositoryBoundary:
    """Resolve existing paths without allowing access outside one repository."""

    def __init__(self, repository_root: str | Path) -> None:
        try:
            root = Path(repository_root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"repository root cannot be resolved: {exc}") from exc
        if not root.is_dir():
            raise ValueError("repository root must be an existing directory")
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def resolve(self, relative_path: str) -> Path:
        """Return a canonical in-repository path or raise RepositoryAccessError."""

        if not isinstance(relative_path, str) or not relative_path.strip():
            raise RepositoryAccessError("path must be a non-empty string")
        if "\x00" in relative_path:
            raise RepositoryAccessError("path must not contain a null byte")

        platform_path = Path(relative_path)
        windows_path = PureWindowsPath(relative_path)
        posix_path = PurePosixPath(relative_path)
        if (
            platform_path.is_absolute()
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.root
            or windows_path.drive
        ):
            raise RepositoryAccessError("absolute paths are not allowed")
        if ".." in posix_path.parts or ".." in windows_path.parts:
            raise RepositoryAccessError("parent path traversal is not allowed")
        if _is_protected(tuple(platform_path.parts)):
            raise RepositoryAccessError("access to protected repository paths is not allowed")

        try:
            resolved = (self._root / platform_path).resolve(strict=True)
        except FileNotFoundError as exc:
            raise RepositoryAccessError(f"path does not exist: {relative_path!r}") from exc
        except (OSError, RuntimeError) as exc:
            raise RepositoryAccessError(f"path cannot be resolved: {relative_path!r}") from exc

        # 必须在跟随符号链接或 Windows Junction 后再次校验真实路径，
        # 否则表面位于仓库内的链接仍可能读取仓库外文件。
        self._relative_resolved_path(resolved)
        return resolved

    def relative_name(self, resolved_path: Path) -> str:
        """Return a stable POSIX-style name for a verified canonical path."""

        return self._relative_resolved_path(resolved_path).as_posix()

    def _relative_resolved_path(self, resolved_path: Path) -> Path:
        try:
            relative = resolved_path.relative_to(self._root)
        except ValueError as exc:
            raise RepositoryAccessError("path escapes repository root") from exc
        if _is_protected(tuple(relative.parts)):
            raise RepositoryAccessError("access to protected repository paths is not allowed")
        return relative


class SafeReadTools:
    """Build and execute ``list_files`` and ``read_file`` for one repository."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
        max_list_entries: int = DEFAULT_MAX_LIST_ENTRIES,
        max_scanned_entries: int = DEFAULT_MAX_SCANNED_ENTRIES,
    ) -> None:
        self._require_positive_int(max_file_chars, "max_file_chars")
        self._require_positive_int(max_list_entries, "max_list_entries")
        self._require_positive_int(max_scanned_entries, "max_scanned_entries")
        self._boundary = RepositoryBoundary(repository_root)
        self._max_file_chars = max_file_chars
        self._max_list_entries = max_list_entries
        self._max_scanned_entries = max_scanned_entries

    @staticmethod
    def _require_positive_int(value: object, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    def definitions(self) -> tuple[Tool, Tool]:
        """Return model-visible Tool definitions bound to this repository."""

        return (
            Tool(
                name="list_files",
                description=(
                    "Recursively list readable UTF-8 candidate files under a "
                    "repository-relative directory."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": "."}},
                    "additionalProperties": False,
                },
                handler=self.list_files,
            ),
            Tool(
                name="read_file",
                description="Read one UTF-8 text file by repository-relative path.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
                handler=self.read_file,
            ),
        )

    def list_files(self, call: ToolCall) -> ToolResult:
        """Return a deterministic, bounded recursive file listing."""

        started = perf_counter_ns()
        try:
            relative_path = self._path_argument(call, default=".")
            directory = self._boundary.resolve(relative_path)
            if not directory.is_dir():
                raise RepositoryAccessError("list_files path must be a directory")
            names, truncated = self._collect_file_names(directory)
            return self._success(call, "\n".join(names), started, truncated=truncated)
        except (RepositoryAccessError, OSError) as exc:
            return self._failure(call, str(exc), started)

    def read_file(self, call: ToolCall) -> ToolResult:
        """Read bounded UTF-8 text from one verified repository file."""

        started = perf_counter_ns()
        try:
            relative_path = self._path_argument(call)
            file_path = self._boundary.resolve(relative_path)
            if not file_path.is_file():
                raise RepositoryAccessError("read_file path must be a regular file")

            # 仅读取上限再多一个字符：既能判断是否截断，也避免把超大文件
            # 一次性装入内存。UTF-8 解码失败会作为真实 Tool 失败返回。
            with file_path.open("r", encoding="utf-8", errors="strict", newline="") as stream:
                content = stream.read(self._max_file_chars + 1)
            if "\x00" in content:
                raise RepositoryAccessError("file contains null bytes and is not treated as text")
            truncated = len(content) > self._max_file_chars
            if truncated:
                content = content[: self._max_file_chars]
            return self._success(call, content, started, truncated=truncated)
        except UnicodeError:
            return self._failure(call, "file is not valid UTF-8 text", started)
        except (RepositoryAccessError, OSError) as exc:
            return self._failure(call, str(exc), started)

    def _collect_file_names(self, directory: Path) -> tuple[list[str], bool]:
        names: set[str] = set()
        pending = [directory]
        visited_directories: set[Path] = set()
        scanned_entries = 0
        truncated = False

        while pending:
            current = pending.pop()
            if current in visited_directories:
                continue
            visited_directories.add(current)

            # 对每个子项都解析真实路径；访问越界链接时直接忽略，且通过
            # visited 集合阻止仓库内循环链接导致无限递归。
            children = sorted(current.iterdir(), key=lambda path: path.name.casefold())
            for child in children:
                scanned_entries += 1
                if scanned_entries > self._max_scanned_entries:
                    truncated = True
                    pending.clear()
                    break
                try:
                    resolved = child.resolve(strict=True)
                    canonical_name = self._boundary.relative_name(resolved)
                except (FileNotFoundError, OSError, RuntimeError, RepositoryAccessError):
                    continue

                if resolved.is_dir():
                    pending.append(resolved)
                elif resolved.is_file():
                    names.add(canonical_name)
                    if len(names) > self._max_list_entries:
                        truncated = True
                        pending.clear()
                        break

        ordered_names = sorted(names)
        return ordered_names[: self._max_list_entries], truncated

    @staticmethod
    def _path_argument(call: ToolCall, *, default: str | None = None) -> str:
        unexpected = sorted(set(call.arguments) - {"path"})
        if unexpected:
            raise RepositoryAccessError(
                f"unexpected tool arguments: {', '.join(unexpected)}"
            )
        if "path" not in call.arguments:
            if default is None:
                raise RepositoryAccessError("missing required path argument")
            return default
        value = call.arguments["path"]
        if not isinstance(value, str) or not value.strip():
            raise RepositoryAccessError("path argument must be a non-empty string")
        return value

    @staticmethod
    def _elapsed_ms(started: int) -> int:
        return max(0, (perf_counter_ns() - started) // 1_000_000)

    def _success(
        self,
        call: ToolCall,
        output: str,
        started: int,
        *,
        truncated: bool = False,
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


def build_safe_read_tools(
    repository_root: str | Path,
    *,
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
    max_list_entries: int = DEFAULT_MAX_LIST_ENTRIES,
    max_scanned_entries: int = DEFAULT_MAX_SCANNED_ENTRIES,
) -> tuple[Tool, Tool]:
    """Build the two Phase 1.4 tools for a fixed repository root."""

    return SafeReadTools(
        repository_root,
        max_file_chars=max_file_chars,
        max_list_entries=max_list_entries,
        max_scanned_entries=max_scanned_entries,
    ).definitions()
