import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.agent.models import ToolCall
from app.tools import ApplyPatchTool, ToolRegistry, build_apply_patch_tool


class ApplyPatchToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.repository = Path(self._temporary_directory.name) / "repository"
        self.repository.mkdir()
        (self.repository / "src").mkdir()
        (self.repository / "src" / "app.py").write_bytes(
            b"def answer():\n"
            b"    return 41\n"
            b"\n"
            b"def label():\n"
            b"    return \"old\"\n"
        )

    @staticmethod
    def _call(patch: object = None, **arguments: object) -> ToolCall:
        values = dict(arguments)
        if patch is not None:
            values["patch"] = patch
        return ToolCall(id="call-patch", name="apply_patch", arguments=values)

    def _tool(self, **limits: int):
        return build_apply_patch_tool(self.repository, **limits)

    def test_builds_contract_applies_real_change_and_returns_diff(self) -> None:
        registry = ToolRegistry([self._tool()])
        tool = registry.get("apply_patch")
        patch = (
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def answer():\n"
            "-    return 41\n"
            "+    return 42\n"
        )

        result = tool.handler(self._call(patch))

        self.assertEqual(registry.names, ("apply_patch",))
        self.assertEqual(tool.input_schema["required"], ["patch"])
        self.assertTrue(result.success)
        self.assertFalse(result.truncated)
        self.assertEqual(result.tool_call_id, "call-patch")
        self.assertEqual(result.tool_name, "apply_patch")
        self.assertIn("-    return 41", result.output)
        self.assertIn("+    return 42", result.output)
        self.assertEqual(
            (self.repository / "src" / "app.py").read_text(encoding="utf-8"),
            "def answer():\n    return 42\n\ndef label():\n    return \"old\"\n",
        )

    def test_applies_multiple_hunks_with_insert_and_delete_ranges(self) -> None:
        patch = (
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def answer():\n"
            "-    return 41\n"
            "+    return 42\n"
            "@@ -3,0 +4 @@\n"
            "+# inserted between functions\n"
            "@@ -5 +5,0 @@\n"
            "-    return \"old\"\n"
        )

        result = self._tool().handler(self._call(patch))

        self.assertTrue(result.success)
        content = (self.repository / "src" / "app.py").read_text(encoding="utf-8")
        self.assertIn("return 42", content)
        self.assertIn("# inserted between functions", content)
        self.assertIn("def label():", content)
        self.assertNotIn('return "old"', content)

    def test_rejects_conflict_without_changing_the_file(self) -> None:
        target = self.repository / "src" / "app.py"
        before = target.read_bytes()
        patch = (
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def answer():\n"
            "-    return 41\n"
            "+    return 42\n"
            "@@ -4,2 +4,2 @@\n"
            " def label():\n"
            "-    return \"missing\"\n"
            "+    return \"new\"\n"
        )

        result = self._tool().handler(self._call(patch))

        self.assertFalse(result.success)
        self.assertIn("patch conflict", result.error)
        self.assertEqual(result.output, "")
        self.assertEqual(target.read_bytes(), before)

    def test_rejects_invalid_patch_shapes_without_changing_the_file(self) -> None:
        target = self.repository / "src" / "app.py"
        before = target.read_bytes()
        cases = [
            (self._call(), "non-empty string"),
            (self._call(""), "non-empty string"),
            (self._call(3), "non-empty string"),
            (self._call("--- a/src/app.py\n", extra=True), "unexpected tool arguments"),
            (self._call("not a diff\n"), "file headers"),
            (
                self._call(
                    "--- a/src/app.py\n"
                    "+++ b/src/other.py\n"
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                ),
                "same file",
            ),
            (
                self._call(
                    "--- a/src/app.py\n"
                    "+++ b/src/app.py\n"
                    "@@ -1,2 +1,1 @@\n"
                    "-def answer():\n"
                    "+changed\n"
                ),
                "line counts",
            ),
            (
                self._call(
                    "--- a/src/app.py\n"
                    "+++ b/src/app.py\n"
                    "@@ -1 +1 @@\n"
                    " def answer():\n"
                ),
                "added or removed",
            ),
            (
                self._call(
                    "--- a/src/app.py\n"
                    "+++ b/src/app.py\n"
                    "@@ -1 +1 @@\n"
                    "-def answer():\n"
                    "+changed\n"
                    "--- a/src/other.py\n"
                    "+++ b/src/other.py\n"
                ),
                "multi-file",
            ),
            (
                self._call(
                    "--- /dev/null\n"
                    "+++ b/src/new.py\n"
                    "@@ -0,0 +1 @@\n"
                    "+new\n"
                ),
                "creation and deletion",
            ),
        ]

        for call, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                result = self._tool().handler(call)
                self.assertFalse(result.success)
                self.assertIn(expected_error, result.error)
                self.assertEqual(target.read_bytes(), before)

    def test_rejects_escape_absolute_protected_and_missing_paths(self) -> None:
        outside = Path(self._temporary_directory.name) / "outside.py"
        outside.write_text("old\n", encoding="utf-8")
        (self.repository / ".env").write_text("TOKEN=old\n", encoding="utf-8")
        cases = [
            ("../outside.py", "parent path traversal"),
            (str(outside.resolve()), "absolute paths"),
            (".env", "protected repository paths"),
            ("missing.py", "does not exist"),
        ]

        for path, expected_error in cases:
            with self.subTest(path=path):
                patch = (
                    f"--- a/{path}\n"
                    f"+++ b/{path}\n"
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                )
                result = self._tool().handler(self._call(patch))
                self.assertFalse(result.success)
                self.assertIn(expected_error, result.error)

        self.assertEqual(outside.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(
            (self.repository / ".env").read_text(encoding="utf-8"),
            "TOKEN=old\n",
        )

    def test_rejects_repository_links_even_when_the_target_is_inside(self) -> None:
        inside_link = self.repository / "linked"
        self._create_directory_link(inside_link, self.repository / "src")
        outside = Path(self._temporary_directory.name) / "outside"
        outside.mkdir()
        (outside / "app.py").write_text("old\n", encoding="utf-8")
        outside_link = self.repository / "escape"
        self._create_directory_link(outside_link, outside)
        inside_patch = (
            "--- a/linked/app.py\n"
            "+++ b/linked/app.py\n"
            "@@ -1 +1 @@\n"
            "-def answer():\n"
            "+def changed():\n"
        )
        outside_patch = (
            "--- a/escape/app.py\n"
            "+++ b/escape/app.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        inside_result = self._tool().handler(self._call(inside_patch))
        outside_result = self._tool().handler(self._call(outside_patch))

        self.assertFalse(inside_result.success)
        self.assertIn("symbolic links or junctions", inside_result.error)
        self.assertFalse(outside_result.success)
        self.assertIn("escapes repository root", outside_result.error)
        self.assertTrue(
            (self.repository / "src" / "app.py")
            .read_text(encoding="utf-8")
            .startswith("def answer()")
        )
        self.assertEqual((outside / "app.py").read_text(encoding="utf-8"), "old\n")

    def test_rejects_non_text_and_oversized_files_without_writing(self) -> None:
        invalid = self.repository / "invalid.bin"
        invalid.write_bytes(b"old\xff\n")
        null_file = self.repository / "null.bin"
        null_file.write_bytes(b"old\x00\n")
        large = self.repository / "large.txt"
        large.write_text("old value\n", encoding="utf-8")

        def patch_for(path: str) -> str:
            return (
                f"--- a/{path}\n"
                f"+++ b/{path}\n"
                "@@ -1 +1 @@\n"
                "-old value\n"
                "+new value\n"
            )

        invalid_result = self._tool().handler(self._call(patch_for("invalid.bin")))
        null_result = self._tool().handler(self._call(patch_for("null.bin")))
        large_result = self._tool(max_file_chars=3).handler(
            self._call(patch_for("large.txt"))
        )

        self.assertFalse(invalid_result.success)
        self.assertIn("not valid UTF-8", invalid_result.error)
        self.assertFalse(null_result.success)
        self.assertIn("null bytes", null_result.error)
        self.assertFalse(large_result.success)
        self.assertIn("character limit", large_result.error)
        self.assertEqual(large.read_text(encoding="utf-8"), "old value\n")

    def test_preserves_crlf_and_supports_no_final_newline(self) -> None:
        crlf = self.repository / "crlf.txt"
        crlf.write_bytes(b"first\r\nold\r\n")
        no_newline = self.repository / "tail.txt"
        no_newline.write_bytes(b"old")

        crlf_patch = (
            "--- a/crlf.txt\n"
            "+++ b/crlf.txt\n"
            "@@ -1,2 +1,2 @@\n"
            " first\n"
            "-old\n"
            "+new\n"
        )
        tail_patch = (
            "--- a/tail.txt\n"
            "+++ b/tail.txt\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
            "\\ No newline at end of file\n"
        )

        crlf_result = self._tool().handler(self._call(crlf_patch))
        tail_result = self._tool().handler(self._call(tail_patch))

        self.assertTrue(crlf_result.success)
        self.assertEqual(crlf.read_bytes(), b"first\r\nnew\r\n")
        self.assertTrue(tail_result.success)
        self.assertEqual(no_newline.read_bytes(), b"new")
        self.assertIn("\\ No newline at end of file", tail_result.output)

    def test_enforces_input_and_output_limits(self) -> None:
        patch = (
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-def answer():\n"
            "+def renamed_answer():\n"
        )

        input_limited = self._tool(max_patch_chars=10).handler(self._call(patch))
        output_limited = self._tool(max_output_chars=10).handler(self._call(patch))

        self.assertFalse(input_limited.success)
        self.assertIn("patch exceeds", input_limited.error)
        self.assertTrue(output_limited.success)
        self.assertTrue(output_limited.truncated)
        self.assertEqual(len(output_limited.output), 10)
        self.assertTrue(
            (self.repository / "src" / "app.py")
            .read_text(encoding="utf-8")
            .startswith("def renamed_answer()")
        )

    def test_rejects_invalid_roots_and_limits(self) -> None:
        file_root = self.repository / "src" / "app.py"

        with self.assertRaisesRegex(ValueError, "existing directory"):
            ApplyPatchTool(file_root)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            ApplyPatchTool(self.repository, max_patch_chars=0)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            ApplyPatchTool(self.repository, max_output_chars=False)

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

        # 清理时仅删除链接入口，不跟随 Junction 删除真实测试目录。
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
