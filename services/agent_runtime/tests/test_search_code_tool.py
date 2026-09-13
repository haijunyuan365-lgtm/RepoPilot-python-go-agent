import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.agent.models import ToolCall
from app.tools import SearchCodeTool, ToolRegistry, build_search_code_tool


class SearchCodeToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.repository = Path(self._temporary_directory.name) / "repository"
        self.repository.mkdir()
        (self.repository / "src").mkdir()
        (self.repository / "docs").mkdir()
        (self.repository / "src" / "alpha.py").write_text(
            "alpha target omega\nTARGET is different\n", encoding="utf-8"
        )
        (self.repository / "src" / "zeta.py").write_text(
            "target at start\n", encoding="utf-8"
        )
        (self.repository / "docs" / "guide.md").write_text(
            "use target here\n", encoding="utf-8"
        )
        (self.repository / "README.md").write_text("# Fixture\n", encoding="utf-8")

    @staticmethod
    def _call(**arguments: object) -> ToolCall:
        return ToolCall(id="call-search", name="search_code", arguments=arguments)

    def _tool(self, **limits: int):
        return build_search_code_tool(self.repository, **limits)

    def test_builds_contract_and_returns_deterministic_structured_matches(self) -> None:
        registry = ToolRegistry([self._tool()])
        tool = registry.get("search_code")

        result = tool.handler(self._call(query="target"))

        self.assertEqual(registry.names, ("search_code",))
        self.assertEqual(tool.input_schema["required"], ["query"])
        self.assertTrue(result.success)
        self.assertFalse(result.truncated)
        self.assertEqual(result.tool_call_id, "call-search")
        self.assertEqual(result.tool_name, "search_code")
        self.assertEqual(
            json.loads(result.output),
            [
                {
                    "path": "docs/guide.md",
                    "line": 1,
                    "column": 5,
                    "text": "use target here",
                },
                {
                    "path": "src/alpha.py",
                    "line": 1,
                    "column": 7,
                    "text": "alpha target omega",
                },
                {
                    "path": "src/zeta.py",
                    "line": 1,
                    "column": 1,
                    "text": "target at start",
                },
            ],
        )

    def test_returns_successful_empty_json_for_no_match(self) -> None:
        result = self._tool().handler(self._call(query="not-present"))

        self.assertTrue(result.success)
        self.assertEqual(json.loads(result.output), [])
        self.assertFalse(result.truncated)

    def test_scopes_search_to_a_file_or_subdirectory(self) -> None:
        file_result = self._tool().handler(
            self._call(query="target", path="src/zeta.py")
        )
        directory_result = self._tool().handler(
            self._call(query="target", path="docs")
        )

        self.assertEqual(
            [match["path"] for match in json.loads(file_result.output)],
            ["src/zeta.py"],
        )
        self.assertEqual(
            [match["path"] for match in json.loads(directory_result.output)],
            ["docs/guide.md"],
        )

    def test_uses_case_sensitive_literal_line_matching(self) -> None:
        (self.repository / "literal.txt").write_text(
            "needle.* is literal\nNeedle.* differs\n", encoding="utf-8"
        )

        result = self._tool().handler(self._call(query="needle.*"))

        matches = json.loads(result.output)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["path"], "literal.txt")
        self.assertEqual(matches[0]["column"], 1)

    def test_rejects_invalid_arguments_and_paths(self) -> None:
        outside = Path(self._temporary_directory.name) / "outside.txt"
        outside.write_text("target", encoding="utf-8")
        cases = [
            ({}, "query argument must be a non-empty string"),
            ({"query": ""}, "query argument must be a non-empty string"),
            ({"query": 3}, "query argument must be a non-empty string"),
            ({"query": "two\nlines"}, "query argument must be a single line"),
            (
                {"query": "target", "path": 3},
                "path argument must be a non-empty string",
            ),
            ({"query": "target", "extra": True}, "unexpected tool arguments"),
            ({"query": "target", "path": "../outside.txt"}, "parent path traversal"),
            ({"query": "target", "path": str(outside)}, "absolute paths"),
        ]

        for arguments, expected_error in cases:
            with self.subTest(arguments=arguments):
                result = self._tool().handler(self._call(**arguments))
                self.assertFalse(result.success)
                self.assertEqual(result.output, "")
                self.assertIn(expected_error, result.error)

    def test_blocks_protected_files_and_repository_escape_links(self) -> None:
        (self.repository / ".env").write_text("target=secret", encoding="utf-8")
        outside = Path(self._temporary_directory.name) / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("target", encoding="utf-8")
        link = self.repository / "escape"
        self._create_directory_link(link, outside)

        protected = self._tool().handler(self._call(query="target", path=".env"))
        escaped = self._tool().handler(self._call(query="target", path="escape"))
        root_search = self._tool().handler(self._call(query="secret"))

        self.assertFalse(protected.success)
        self.assertIn("protected repository paths", protected.error)
        self.assertFalse(escaped.success)
        self.assertIn("escapes repository root", escaped.error)
        self.assertTrue(root_search.success)
        self.assertEqual(json.loads(root_search.output), [])

    def test_rejects_explicit_non_text_files(self) -> None:
        (self.repository / "invalid.bin").write_bytes(b"target\xffhidden")
        (self.repository / "null.bin").write_bytes(b"target\x00hidden")

        invalid = self._tool().handler(
            self._call(query="target", path="invalid.bin")
        )
        null_bytes = self._tool().handler(
            self._call(query="target", path="null.bin")
        )
        directory_search = self._tool().handler(self._call(query="target"))

        self.assertFalse(invalid.success)
        self.assertIn("not valid UTF-8", invalid.error)
        self.assertFalse(null_bytes.success)
        self.assertIn("null bytes", null_bytes.error)
        self.assertTrue(directory_search.success)
        self.assertNotIn("invalid.bin", directory_search.output)
        self.assertNotIn("null.bin", directory_search.output)

    def test_bounds_match_count_and_keeps_output_valid_json(self) -> None:
        limited_matches = self._tool(max_matches=1).handler(
            self._call(query="target")
        )
        limited_output = self._tool(max_output_chars=2).handler(
            self._call(query="target")
        )

        self.assertTrue(limited_matches.success)
        self.assertEqual(len(json.loads(limited_matches.output)), 1)
        self.assertTrue(limited_matches.truncated)
        self.assertTrue(limited_output.success)
        self.assertEqual(json.loads(limited_output.output), [])
        self.assertTrue(limited_output.truncated)

    def test_bounds_file_content_and_candidate_file_scanning(self) -> None:
        (self.repository / "long.txt").write_text("xxxxxTARGET", encoding="utf-8")
        many = self.repository / "many"
        many.mkdir()
        (many / "a.txt").write_text("first", encoding="utf-8")
        (many / "b.txt").write_text("target", encoding="utf-8")

        file_limited = self._tool(max_file_chars=5).handler(
            self._call(query="TARGET", path="long.txt")
        )
        scan_limited = self._tool(max_scanned_files=1).handler(
            self._call(query="target", path="many")
        )

        self.assertEqual(json.loads(file_limited.output), [])
        self.assertTrue(file_limited.truncated)
        self.assertEqual(json.loads(scan_limited.output), [])
        self.assertTrue(scan_limited.truncated)

    def test_rejects_invalid_roots_and_limits(self) -> None:
        file_root = self.repository / "README.md"

        with self.assertRaisesRegex(ValueError, "existing directory"):
            SearchCodeTool(file_root)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            SearchCodeTool(self.repository, max_matches=0)
        with self.assertRaisesRegex(ValueError, "empty JSON array"):
            SearchCodeTool(self.repository, max_output_chars=1)

    def _create_directory_link(self, link: Path, target: Path) -> None:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as symlink_error:
            if os.name != "nt":
                self.fail(f"cannot create the required symlink fixture: {symlink_error}")
            completed = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                self.fail(
                    "cannot create the required symlink/junction fixture: "
                    f"{completed.stderr or completed.stdout or symlink_error}"
                )

        # 只移除链接本身，避免临时目录清理阶段跟随 Junction 删除目标内容。
        self.addCleanup(self._remove_directory_link, link)

    @staticmethod
    def _remove_directory_link(link: Path) -> None:
        if not os.path.lexists(link):
            return
        if link.is_symlink():
            link.unlink()
        else:
            os.rmdir(link)


if __name__ == "__main__":
    unittest.main()
