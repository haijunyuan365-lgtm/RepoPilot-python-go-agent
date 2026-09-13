"""Whitelisted test-command execution for the Phase 1 runtime."""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter_ns
from typing import TextIO

from app.agent.models import ToolCall, ToolResult

from .registry import Tool
from .safe_read import RepositoryBoundary


DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_OUTPUT_CHARS = 100_000
_READ_CHUNK_CHARS = 8_192
_PIPE_DRAIN_GRACE_SECONDS = 1.0
_INHERITED_ENVIRONMENT_NAMES = (
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
)


class TestExecutionError(Exception):
    """Raised when a run_test request is invalid or cannot be launched."""


@dataclass
class _BoundedCapture:
    """Keep a bounded text prefix while the reader continues draining its pipe."""

    limit: int
    chunks: list[str] = field(default_factory=list)
    length: int = 0
    truncated: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append(self, chunk: str) -> None:
        with self._lock:
            remaining = self.limit - self.length
            if remaining > 0:
                kept = chunk[:remaining]
                self.chunks.append(kept)
                self.length += len(kept)
            if len(chunk) > max(remaining, 0):
                self.truncated = True

    def mark_truncated(self) -> None:
        with self._lock:
            self.truncated = True

    def snapshot(self) -> tuple[str, bool]:
        with self._lock:
            return "".join(self.chunks), self.truncated


class RunTestTool:
    """Build and execute one repository-bounded ``run_test`` tool."""

    def __init__(
        self,
        repository_root: str | Path,
        allowed_commands: Mapping[str, Sequence[str]],
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        if (
            isinstance(max_output_chars, bool)
            or not isinstance(max_output_chars, int)
            or max_output_chars <= 0
        ):
            raise ValueError("max_output_chars must be a positive integer")
        if not isinstance(allowed_commands, Mapping) or not allowed_commands:
            raise ValueError("allowed_commands must be a non-empty mapping")

        self._boundary = RepositoryBoundary(repository_root)
        self._timeout_seconds = float(timeout_seconds)
        self._max_output_chars = max_output_chars
        self._display_commands: dict[str, tuple[str, ...]] = {}
        self._execution_commands: dict[str, tuple[str, ...]] = {}

        for test_name, command in allowed_commands.items():
            normalized_name = self._validate_test_name(test_name)
            if normalized_name in self._execution_commands:
                raise ValueError(f"duplicate test name: {normalized_name!r}")
            display_command, execution_command = self._normalize_command(
                command,
                normalized_name,
            )
            self._display_commands[normalized_name] = display_command
            self._execution_commands[normalized_name] = execution_command

            # 即使没有测试输出，命令、退出码和超时状态也必须完整保留；
            # 配置阶段提前拒绝连最小结构化 Observation 都装不下的上限。
            minimum_output = self._serialize_payload(
                test_name=normalized_name,
                command=display_command,
                # 子进程退出码在不同平台可能是有符号 32 位值；用最长
                # 合法表示校验，避免极小上限只在异常退出时才暴露问题。
                exit_code=-2_147_483_648,
                timed_out=False,
                stdout="",
                stderr="",
                stdout_truncated=False,
                stderr_truncated=False,
            )
            if len(minimum_output) > max_output_chars:
                raise ValueError(
                    "max_output_chars is too small for configured command metadata"
                )

        self._environment = self._minimal_environment()

    def definition(self) -> Tool:
        """Return the model-visible Tool definition bound to this repository."""

        return Tool(
            name="run_test",
            description=(
                "Run one preconfigured test command in the repository root. "
                "Only the listed test_name values are allowed; arbitrary commands "
                "and arguments are not accepted."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "test_name": {
                        "type": "string",
                        "enum": list(self._execution_commands),
                    }
                },
                "required": ["test_name"],
                "additionalProperties": False,
            },
            handler=self.run_test,
        )

    def run_test(self, call: ToolCall) -> ToolResult:
        """Run one exact whitelisted argv and return bounded execution evidence."""

        started = perf_counter_ns()
        try:
            test_name = self._test_name_argument(call)
            display_command = self._display_commands[test_name]
            execution_command = self._execution_commands[test_name]
            return self._execute(
                call,
                test_name,
                display_command,
                execution_command,
                started,
            )
        except TestExecutionError as exc:
            return self._failure(call, str(exc), started)

    def _execute(
        self,
        call: ToolCall,
        test_name: str,
        display_command: tuple[str, ...],
        execution_command: tuple[str, ...],
        started: int,
    ) -> ToolResult:
        popen_options: dict[str, object] = {}
        if os.name == "posix":
            popen_options["start_new_session"] = True
        elif os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            # cwd、argv、环境和 shell 策略均由服务端固定；模型无法追加参数，
            # 也无法借助 ;、&&、重定向等 shell 语法扩展执行范围。
            process = subprocess.Popen(
                execution_command,
                cwd=self._boundary.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=self._environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                **popen_options,
            )
        except OSError as exc:
            output, truncated = self._render_output(
                test_name=test_name,
                command=display_command,
                exit_code=None,
                timed_out=False,
                stdout=_BoundedCapture(self._max_output_chars),
                stderr=_BoundedCapture(self._max_output_chars),
            )
            return self._failure(
                call,
                f"test command could not start: {type(exc).__name__}: {exc}",
                started,
                output=output,
                truncated=truncated,
            )

        if process.stdout is None or process.stderr is None:
            process.kill()
            process.wait()
            raise RuntimeError("subprocess pipes were not created")

        stdout = _BoundedCapture(self._max_output_chars)
        stderr = _BoundedCapture(self._max_output_chars)
        readers = (
            threading.Thread(
                target=self._drain_stream,
                args=(process.stdout, stdout),
                name=f"run-test-{process.pid}-stdout",
                daemon=True,
            ),
            threading.Thread(
                target=self._drain_stream,
                args=(process.stderr, stderr),
                name=f"run-test-{process.pid}-stderr",
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()

        timed_out = False
        try:
            exit_code = process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            # 清理本次测试派生的进程，避免子进程继续占用输出管道并让
            # timeout 失效；Sandbox 级强隔离与资源限制仍留给 Phase 5。
            self._terminate_timed_out_process(process)
            process.wait()
            exit_code = None

        for reader, capture in zip(readers, (stdout, stderr)):
            reader.join(timeout=_PIPE_DRAIN_GRACE_SECONDS)
            if reader.is_alive():
                # 某些测试会派生并留下继承 pipe 的后台进程。工具不能因该
                # pipe 永不关闭而无限等待；保留已有前缀并显式标记截断。
                capture.mark_truncated()

        output, truncated = self._render_output(
            test_name=test_name,
            command=display_command,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
        )
        if timed_out:
            return self._failure(
                call,
                f"test command timed out after {self._timeout_seconds:g} seconds",
                started,
                output=output,
                truncated=truncated,
            )
        if exit_code != 0:
            return self._failure(
                call,
                f"test command exited with code {exit_code}",
                started,
                output=output,
                truncated=truncated,
            )
        return self._success(
            call,
            output,
            started,
            truncated=truncated,
        )

    def _render_output(
        self,
        *,
        test_name: str,
        command: tuple[str, ...],
        exit_code: int | None,
        timed_out: bool,
        stdout: _BoundedCapture,
        stderr: _BoundedCapture,
    ) -> tuple[str, bool]:
        stdout_text, stdout_was_truncated = stdout.snapshot()
        stderr_text, stderr_was_truncated = stderr.snapshot()

        # JSON 转义会让一个原始字符占用多个输出字符，因此用二分搜索找出
        # 在总上限内可保留的最大 stdout/stderr 前缀，始终返回可解析 JSON。
        low = 0
        high = len(stdout_text) + len(stderr_text)
        best_output = ""
        best_truncated = True
        while low <= high:
            retained = (low + high) // 2
            stdout_length, stderr_length = self._allocate_stream_chars(
                retained,
                len(stdout_text),
                len(stderr_text),
            )
            stdout_truncated = (
                stdout_was_truncated or stdout_length < len(stdout_text)
            )
            stderr_truncated = (
                stderr_was_truncated or stderr_length < len(stderr_text)
            )
            candidate = self._serialize_payload(
                test_name=test_name,
                command=command,
                exit_code=exit_code,
                timed_out=timed_out,
                stdout=stdout_text[:stdout_length],
                stderr=stderr_text[:stderr_length],
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )
            if len(candidate) <= self._max_output_chars:
                best_output = candidate
                best_truncated = stdout_truncated or stderr_truncated
                low = retained + 1
            else:
                high = retained - 1

        if not best_output:
            raise RuntimeError("configured output limit cannot hold execution metadata")
        return best_output, best_truncated

    @staticmethod
    def _allocate_stream_chars(
        retained: int,
        stdout_length: int,
        stderr_length: int,
    ) -> tuple[int, int]:
        stdout_kept = min(stdout_length, (retained + 1) // 2)
        stderr_kept = min(stderr_length, retained // 2)
        remaining = retained - stdout_kept - stderr_kept
        if remaining:
            stdout_extra = min(remaining, stdout_length - stdout_kept)
            stdout_kept += stdout_extra
            remaining -= stdout_extra
        if remaining:
            stderr_kept += min(remaining, stderr_length - stderr_kept)
        return stdout_kept, stderr_kept

    @staticmethod
    def _serialize_payload(
        *,
        test_name: str,
        command: tuple[str, ...],
        exit_code: int | None,
        timed_out: bool,
        stdout: str,
        stderr: str,
        stdout_truncated: bool,
        stderr_truncated: bool,
    ) -> str:
        return json.dumps(
            {
                "command": list(command),
                "exit_code": exit_code,
                "stderr": stderr,
                "stderr_truncated": stderr_truncated,
                "stdout": stdout,
                "stdout_truncated": stdout_truncated,
                "test_name": test_name,
                "timed_out": timed_out,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _drain_stream(stream: TextIO, capture: _BoundedCapture) -> None:
        try:
            while True:
                chunk = stream.read(_READ_CHUNK_CHARS)
                if not chunk:
                    return
                # 达到保留上限后仍持续读取并丢弃后续内容，防止子进程因
                # pipe 缓冲区写满而阻塞，最终把正常测试误判成 timeout。
                capture.append(chunk)
        finally:
            stream.close()

    def _terminate_timed_out_process(self, process: subprocess.Popen[str]) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            elif os.name == "nt":
                system_root = self._environment.get("SYSTEMROOT")
                taskkill = (
                    Path(system_root) / "System32" / "taskkill.exe"
                    if system_root
                    else None
                )
                if taskkill is not None and taskkill.is_file():
                    # 参数完全由工具生成且不经过 shell；/T 清理测试进程树，
                    # /F 确保超时后不再等待测试代码自行配合退出。
                    subprocess.run(
                        (str(taskkill), "/PID", str(process.pid), "/T", "/F"),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        shell=False,
                        env=self._environment,
                        timeout=5,
                        check=False,
                    )
                if process.poll() is None:
                    process.kill()
            else:
                process.kill()
        except (OSError, subprocess.SubprocessError):
            if process.poll() is None:
                process.kill()

    def _test_name_argument(self, call: ToolCall) -> str:
        unexpected = sorted(set(call.arguments) - {"test_name"})
        if unexpected:
            raise TestExecutionError(
                f"unexpected tool arguments: {', '.join(unexpected)}"
            )
        value = call.arguments.get("test_name")
        if not isinstance(value, str) or not value.strip():
            raise TestExecutionError("test_name argument must be a non-empty string")
        if value not in self._execution_commands:
            raise TestExecutionError(f"test command is not allowed: {value!r}")
        return value

    @staticmethod
    def _validate_test_name(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("test command names must be non-empty strings")
        if "\x00" in value:
            raise ValueError("test command names must not contain null bytes")
        return value

    @staticmethod
    def _normalize_command(
        command: Sequence[str],
        test_name: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
            raise ValueError(f"command for {test_name!r} must be an argument sequence")
        display = tuple(command)
        if not display:
            raise ValueError(f"command for {test_name!r} must not be empty")
        if any(
            not isinstance(part, str) or not part or "\x00" in part
            for part in display
        ):
            raise ValueError(
                f"command for {test_name!r} must contain non-empty strings "
                "without null bytes"
            )

        executable = Path(display[0])
        if executable.is_absolute():
            try:
                resolved = executable.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError(
                    f"executable for {test_name!r} cannot be resolved: {exc}"
                ) from exc
            if not resolved.is_file():
                raise ValueError(f"executable for {test_name!r} must be a file")
        else:
            found = shutil.which(display[0])
            if found is None:
                raise ValueError(
                    f"executable for {test_name!r} was not found on PATH"
                )
            resolved = Path(found).resolve(strict=True)

        # 初始化时解析并冻结可执行文件绝对路径，避免运行时切换到仓库 cwd
        # 后被同名恶意文件或随后变化的 PATH 劫持。
        return display, (str(resolved), *display[1:])

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        environment = {
            name: os.environ[name]
            for name in _INHERITED_ENVIRONMENT_NAMES
            if name in os.environ
        }
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUNBUFFERED"] = "1"
        return environment

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

    def _failure(
        self,
        call: ToolCall,
        error: str,
        started: int,
        *,
        output: str = "",
        truncated: bool = False,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            success=False,
            output=output,
            error=error,
            duration_ms=self._elapsed_ms(started),
            truncated=truncated,
        )


def build_run_test_tool(
    repository_root: str | Path,
    allowed_commands: Mapping[str, Sequence[str]],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> Tool:
    """Build the Phase 1.7 test tool for one fixed repository root."""

    return RunTestTool(
        repository_root,
        allowed_commands,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    ).definition()
