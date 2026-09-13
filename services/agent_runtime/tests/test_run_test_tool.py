import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent.models import ToolCall
from app.tools import RunTestTool, ToolRegistry, build_run_test_tool


class RunTestToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self._temporary.name) / "repo"
        self.repository.mkdir()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _write_script(self, name: str, source: str) -> Path:
        path = self.repository / name
        path.write_text(source, encoding="utf-8")
        return path

    @staticmethod
    def _call(test_name: object = "unit", **extra: object) -> ToolCall:
        return ToolCall(
            id="call-run-test",
            name="run_test",
            arguments={"test_name": test_name, **extra},
        )

    def _build(
        self,
        command: list[str],
        *,
        timeout_seconds: float = 2,
        max_output_chars: int = 10_000,
    ) -> RunTestTool:
        return RunTestTool(
            self.repository,
            {"unit": command},
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        )

    def test_builds_contract_and_runs_passing_test_in_repository_root(self) -> None:
        self._write_script(
            "passing.py",
            """
import os
import sys
from pathlib import Path

print(f"cwd={Path.cwd().name}")
print(f"secret={os.environ.get('REPOPILOT_TEST_SECRET', 'missing')}")
print("warning from stderr", file=sys.stderr)
""".lstrip(),
        )
        with patch.dict(os.environ, {"REPOPILOT_TEST_SECRET": "must-not-leak"}):
            tool = self._build([sys.executable, "passing.py"])
        definition = tool.definition()
        registry = ToolRegistry([definition])

        result = registry.get("run_test").handler(self._call())
        payload = json.loads(result.output)

        self.assertEqual(
            definition.input_schema,
            {
                "type": "object",
                "properties": {
                    "test_name": {"type": "string", "enum": ["unit"]}
                },
                "required": ["test_name"],
                "additionalProperties": False,
            },
        )
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertFalse(result.truncated)
        self.assertEqual(result.tool_call_id, "call-run-test")
        self.assertEqual(result.tool_name, "run_test")
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertEqual(payload["command"], [sys.executable, "passing.py"])
        self.assertEqual(payload["exit_code"], 0)
        self.assertFalse(payload["timed_out"])
        self.assertIn(f"cwd={self.repository.name}", payload["stdout"])
        self.assertIn("secret=missing", payload["stdout"])
        self.assertEqual(payload["stderr"], "warning from stderr\n")

    def test_nonzero_exit_returns_stdout_stderr_and_exit_code(self) -> None:
        self._write_script(
            "failing.py",
            """
import sys

print("assertion context")
print("expected 4 but got 5", file=sys.stderr)
raise SystemExit(3)
""".lstrip(),
        )

        result = self._build([sys.executable, "failing.py"]).run_test(
            self._call()
        )
        payload = json.loads(result.output)

        self.assertFalse(result.success)
        self.assertEqual(result.error, "test command exited with code 3")
        self.assertEqual(payload["exit_code"], 3)
        self.assertFalse(payload["timed_out"])
        self.assertEqual(payload["stdout"], "assertion context\n")
        self.assertEqual(payload["stderr"], "expected 4 but got 5\n")

    def test_timeout_terminates_process_and_preserves_partial_output(self) -> None:
        self._write_script(
            "slow.py",
            """
import time

print("started before timeout", flush=True)
time.sleep(5)
print("should not finish")
""".lstrip(),
        )
        tool = self._build(
            [sys.executable, "slow.py"],
            timeout_seconds=0.1,
        )

        started = time.monotonic()
        result = tool.run_test(self._call())
        elapsed = time.monotonic() - started
        payload = json.loads(result.output)

        self.assertFalse(result.success)
        self.assertIn("timed out after 0.1 seconds", result.error)
        self.assertLess(elapsed, 3)
        self.assertIsNone(payload["exit_code"])
        self.assertTrue(payload["timed_out"])
        self.assertEqual(payload["stdout"], "started before timeout\n")
        self.assertNotIn("should not finish", payload["stdout"])

    def test_rejects_unknown_or_invalid_arguments_without_execution(self) -> None:
        marker = self.repository / "executed.txt"
        self._write_script(
            "marker.py",
            "from pathlib import Path\nPath('executed.txt').write_text('ran')\n",
        )
        tool = self._build([sys.executable, "marker.py"])
        calls = (
            self._call("integration"),
            self._call(""),
            self._call(7),
            self._call(unit="unexpected"),
            ToolCall(id="missing", name="run_test", arguments={}),
        )

        for call in calls:
            with self.subTest(arguments=call.arguments):
                result = tool.run_test(call)
                self.assertFalse(result.success)
                self.assertEqual(result.output, "")

        self.assertIn("not allowed", tool.run_test(calls[0]).error)
        self.assertFalse(marker.exists())

    def test_command_is_fixed_and_shell_syntax_is_only_a_literal_argument(self) -> None:
        marker = self.repository / "injected.txt"
        self._write_script(
            "arguments.py",
            "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
        )
        literal = "; echo injected > injected.txt"
        result = self._build(
            [sys.executable, "arguments.py", literal]
        ).run_test(self._call())
        payload = json.loads(result.output)

        self.assertTrue(result.success)
        self.assertEqual(json.loads(payload["stdout"]), [literal])
        self.assertFalse(marker.exists())

    def test_large_streams_are_drained_but_return_bounded_valid_json(self) -> None:
        self._write_script(
            "noisy.py",
            """
import sys

sys.stdout.write("o" * 50000)
sys.stderr.write("e" * 50000)
""".lstrip(),
        )
        tool = self._build(
            [sys.executable, "noisy.py"],
            max_output_chars=500,
        )

        result = tool.run_test(self._call())
        payload = json.loads(result.output)

        self.assertTrue(result.success)
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.output), 500)
        self.assertTrue(payload["stdout_truncated"])
        self.assertTrue(payload["stderr_truncated"])
        self.assertTrue(payload["stdout"])
        self.assertTrue(payload["stderr"])

    def test_replaces_invalid_utf8_output_instead_of_losing_result(self) -> None:
        self._write_script(
            "bytes.py",
            "import os\nos.write(1, b'valid\\xfftail')\n",
        )

        result = self._build([sys.executable, "bytes.py"]).run_test(self._call())
        payload = json.loads(result.output)

        self.assertTrue(result.success)
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["stdout"], "valid\ufffdtail")

    def test_selects_only_the_requested_preconfigured_command(self) -> None:
        self._write_script("unit.py", "print('unit selected')\n")
        self._write_script("integration.py", "print('integration selected')\n")
        tool = RunTestTool(
            self.repository,
            {
                "unit": [sys.executable, "unit.py"],
                "integration": [sys.executable, "integration.py"],
            },
        )

        result = tool.run_test(self._call("integration"))
        payload = json.loads(result.output)

        self.assertTrue(result.success)
        self.assertEqual(payload["test_name"], "integration")
        self.assertEqual(payload["stdout"], "integration selected\n")
        self.assertNotIn("unit selected", payload["stdout"])

    def test_builder_returns_a_registry_ready_tool(self) -> None:
        self._write_script("passing.py", "print('ok')\n")

        tool = build_run_test_tool(
            self.repository,
            {"unit": [sys.executable, "passing.py"]},
        )

        self.assertEqual(tool.name, "run_test")
        self.assertTrue(tool.handler(self._call()).success)

    def test_rejects_invalid_roots_commands_and_limits(self) -> None:
        missing_root = self.repository / "missing"
        invalid_cases = (
            (missing_root, {"unit": [sys.executable]}, {}, "root"),
            (self.repository, {}, {}, "non-empty mapping"),
            (self.repository, {"": [sys.executable]}, {}, "names"),
            (self.repository, {"unit": []}, {}, "must not be empty"),
            (self.repository, {"unit": "python -m unittest"}, {}, "sequence"),
            (self.repository, {"unit": [""]}, {}, "non-empty strings"),
            (self.repository, {"unit": ["missing-repopilot-command"]}, {}, "PATH"),
            (
                self.repository,
                {"unit": [sys.executable]},
                {"timeout_seconds": 0},
                "positive finite",
            ),
            (
                self.repository,
                {"unit": [sys.executable]},
                {"max_output_chars": 1},
                "too small",
            ),
        )

        for root, commands, options, expected in invalid_cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    RunTestTool(root, commands, **options)


if __name__ == "__main__":
    unittest.main()
