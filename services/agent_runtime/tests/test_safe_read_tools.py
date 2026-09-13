import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.agent.models import ToolCall
from app.tools import SafeReadTools, ToolRegistry, build_safe_read_tools


class SafeReadToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.repository = Path(self._temporary_directory.name) / "repository"
        self.repository.mkdir()
        (self.repository / "src").mkdir()
        # 使用字节写入固定 LF，确保测试精确验证 read_file 不改写原始换行。
        (self.repository / "src" / "app.py").write_bytes(
            b"def answer():\n    return 42\n"
        )
        (self.repository / "README.md").write_bytes(b"# Fixture\n")

    @staticmethod
    def _call(name: str, **arguments: object) -> ToolCall:
        return ToolCall(id=f"call-{name}", name=name, arguments=arguments)

    def _registry(self, **limits: int) -> ToolRegistry:
        return ToolRegistry(build_safe_read_tools(self.repository, **limits))

    def test_builds_expected_tool_contracts_and_reads_real_content(self) -> None:
        registry = self._registry()

        listed = registry.get("list_files").handler(self._call("list_files"))
        read = registry.get("read_file").handler(
            self._call("read_file", path="src/app.py")
        )

        self.assertEqual(registry.names, ("list_files", "read_file"))
        self.assertTrue(listed.success)
        self.assertEqual(listed.output.splitlines(), ["README.md", "src/app.py"])
        self.assertFalse(listed.truncated)
        self.assertTrue(read.success)
        self.assertEqual(read.output, "def answer():\n    return 42\n")
        self.assertEqual(read.tool_call_id, "call-read_file")
        self.assertEqual(read.tool_name, "read_file")

    def test_lists_only_the_requested_repository_subdirectory(self) -> None:
        result = self._registry().get("list_files").handler(
            self._call("list_files", path="src")
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output, "src/app.py")

    def test_rejects_parent_traversal_and_absolute_paths(self) -> None:
        outside = Path(self._temporary_directory.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        read_tool = self._registry().get("read_file")
        cases = [
            ("../outside.txt", "parent path traversal"),
            ("src/../README.md", "parent path traversal"),
            (str(outside.resolve()), "absolute paths"),
            (r"C:\outside.txt", "absolute paths"),
            (r"\outside.txt", "absolute paths"),
        ]

        for path, expected_error in cases:
            with self.subTest(path=path):
                result = read_tool.handler(self._call("read_file", path=path))
                self.assertFalse(result.success)
                self.assertIn(expected_error, result.error)
                self.assertEqual(result.output, "")

    def test_rejects_a_real_link_that_escapes_the_repository(self) -> None:
        outside = Path(self._temporary_directory.name) / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("do not read", encoding="utf-8")
        link = self.repository / "escape"
        self._create_directory_link(link, outside)

        registry = self._registry()
        read = registry.get("read_file").handler(
            self._call("read_file", path="escape/secret.txt")
        )
        listed_link = registry.get("list_files").handler(
            self._call("list_files", path="escape")
        )
        listed_root = registry.get("list_files").handler(self._call("list_files"))

        self.assertFalse(read.success)
        self.assertIn("escapes repository root", read.error)
        self.assertFalse(listed_link.success)
        self.assertIn("escapes repository root", listed_link.error)
        self.assertTrue(listed_root.success)
        self.assertNotIn("secret.txt", listed_root.output)

    def test_blocks_git_metadata_and_common_credential_files(self) -> None:
        (self.repository / ".git").mkdir()
        (self.repository / ".git" / "config").write_text(
            "credential = hidden", encoding="utf-8"
        )
        (self.repository / ".env").write_text("TOKEN=hidden", encoding="utf-8")
        (self.repository / "private.pem").write_text("hidden", encoding="utf-8")
        (self.repository / ".env.example").write_text(
            "TOKEN=replace-me", encoding="utf-8"
        )
        registry = self._registry()
        read_tool = registry.get("read_file")

        for path in (".git/config", ".env", "private.pem"):
            with self.subTest(path=path):
                result = read_tool.handler(self._call("read_file", path=path))
                self.assertFalse(result.success)
                self.assertIn("protected repository paths", result.error)

        listed = registry.get("list_files").handler(self._call("list_files"))
        self.assertTrue(listed.success)
        self.assertNotIn(".git/config", listed.output)
        self.assertNotIn(".env\n", f"{listed.output}\n")
        self.assertNotIn("private.pem", listed.output)
        self.assertIn(".env.example", listed.output)

    def test_reports_invalid_arguments_missing_paths_and_wrong_path_kinds(self) -> None:
        registry = self._registry()
        cases = [
            (
                registry.get("read_file"),
                self._call("read_file"),
                "missing required path",
            ),
            (
                registry.get("read_file"),
                self._call("read_file", path=3),
                "non-empty string",
            ),
            (
                registry.get("read_file"),
                self._call("read_file", path="README.md", extra=True),
                "unexpected tool arguments",
            ),
            (
                registry.get("read_file"),
                self._call("read_file", path="src"),
                "regular file",
            ),
            (
                registry.get("list_files"),
                self._call("list_files", path="README.md"),
                "must be a directory",
            ),
            (
                registry.get("read_file"),
                self._call("read_file", path="missing.txt"),
                "does not exist",
            ),
        ]

        for tool, call, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                result = tool.handler(call)
                self.assertFalse(result.success)
                self.assertIn(expected_error, result.error)

    def test_bounds_file_and_listing_output(self) -> None:
        (self.repository / "long.txt").write_text("abcdef", encoding="utf-8")
        registry = self._registry(max_file_chars=5, max_list_entries=2)

        read = registry.get("read_file").handler(
            self._call("read_file", path="long.txt")
        )
        listed = registry.get("list_files").handler(self._call("list_files"))

        self.assertTrue(read.success)
        self.assertEqual(read.output, "abcde")
        self.assertTrue(read.truncated)
        self.assertTrue(listed.success)
        self.assertEqual(len(listed.output.splitlines()), 2)
        self.assertTrue(listed.truncated)

    def test_rejects_binary_content_without_returning_partial_data(self) -> None:
        (self.repository / "binary.bin").write_bytes(b"valid-prefix\xffhidden")
        (self.repository / "null.bin").write_bytes(b"valid\x00utf8")

        read_tool = self._registry().get("read_file")
        invalid_utf8 = read_tool.handler(
            self._call("read_file", path="binary.bin")
        )
        null_bytes = read_tool.handler(self._call("read_file", path="null.bin"))

        self.assertFalse(invalid_utf8.success)
        self.assertEqual(invalid_utf8.output, "")
        self.assertIn("not valid UTF-8", invalid_utf8.error)
        self.assertFalse(null_bytes.success)
        self.assertEqual(null_bytes.output, "")
        self.assertIn("null bytes", null_bytes.error)

    def test_rejects_invalid_roots_and_limits(self) -> None:
        file_root = self.repository / "README.md"
        missing_root = self.repository / "missing"

        with self.assertRaisesRegex(ValueError, "existing directory"):
            SafeReadTools(file_root)
        with self.assertRaisesRegex(ValueError, "cannot be resolved"):
            SafeReadTools(missing_root)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            SafeReadTools(self.repository, max_file_chars=0)

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

        # 测试结束前只移除链接本身，避免临时目录清理逻辑误跟随 Junction。
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
