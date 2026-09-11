import math
import unittest

from app.agent.models import ToolCall, ToolResult
from app.tools import DuplicateToolError, Tool, ToolRegistry, UnknownToolError


def successful_handler(call: ToolCall) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=call.name,
        success=True,
        output="ok",
    )


def make_tool(name: str = "read_file") -> Tool:
    return Tool(
        name=name,
        description=f"Execute {name}.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=successful_handler,
    )


class ToolTests(unittest.TestCase):
    def test_definition_is_provider_neutral_and_detached(self) -> None:
        schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        tool = Tool(
            name="read_file",
            description="Read one repository file.",
            input_schema=schema,
            handler=successful_handler,
        )

        schema["required"].append("encoding")
        exported = tool.to_dict()
        exported["input_schema"]["properties"]["path"]["type"] = "integer"

        self.assertEqual(tool.input_schema["required"], ["path"])
        self.assertEqual(
            tool.input_schema["properties"]["path"]["type"],
            "string",
        )
        self.assertEqual(
            tool.to_dict(),
            {
                "name": "read_file",
                "description": "Read one repository file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        )

    def test_rejects_invalid_definition_boundaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tool.name"):
            Tool(
                name=" ",
                description="Read a file.",
                input_schema={"type": "object"},
                handler=successful_handler,
            )
        with self.assertRaisesRegex(ValueError, "Tool.description"):
            Tool(
                name="read_file",
                description="",
                input_schema={"type": "object"},
                handler=successful_handler,
            )
        with self.assertRaisesRegex(ValueError, "must be an object"):
            Tool(
                name="read_file",
                description="Read a file.",
                input_schema=[],
                handler=successful_handler,
            )
        with self.assertRaisesRegex(ValueError, "type must be 'object'"):
            Tool(
                name="read_file",
                description="Read a file.",
                input_schema={"type": "string"},
                handler=successful_handler,
            )
        with self.assertRaisesRegex(ValueError, "non-JSON"):
            Tool(
                name="read_file",
                description="Read a file.",
                input_schema={"type": "object", "properties": {"path": {str}}},
                handler=successful_handler,
            )
        with self.assertRaisesRegex(ValueError, "NaN or infinity"):
            Tool(
                name="read_file",
                description="Read a file.",
                input_schema={"type": "object", "maximum": math.inf},
                handler=successful_handler,
            )
        with self.assertRaisesRegex(ValueError, "handler must be callable"):
            Tool(
                name="read_file",
                description="Read a file.",
                input_schema={"type": "object"},
                handler=None,
            )


class ToolRegistryTests(unittest.TestCase):
    def test_registers_and_resolves_tools_in_registration_order(self) -> None:
        read_file = make_tool("read_file")
        search_code = make_tool("search_code")
        registry = ToolRegistry([read_file])

        registry.register(search_code)

        self.assertIs(registry.get("read_file"), read_file)
        self.assertIs(registry.get("search_code"), search_code)
        self.assertEqual(registry.names, ("read_file", "search_code"))
        self.assertEqual(len(registry), 2)
        self.assertEqual(
            [schema["name"] for schema in registry.schemas()],
            ["read_file", "search_code"],
        )

    def test_duplicate_registration_is_rejected_without_replacement(self) -> None:
        original = make_tool("read_file")
        duplicate = make_tool("read_file")
        registry = ToolRegistry([original])

        with self.assertRaisesRegex(DuplicateToolError, "already registered"):
            registry.register(duplicate)

        self.assertIs(registry.get("read_file"), original)
        self.assertEqual(len(registry), 1)

    def test_unknown_tool_is_an_explicit_lookup_failure(self) -> None:
        registry = ToolRegistry()

        with self.assertRaisesRegex(UnknownToolError, "unknown tool"):
            registry.get("missing_tool")
        with self.assertRaisesRegex(ValueError, "non-empty"):
            registry.get(" ")

        self.assertEqual(registry.names, ())

    def test_registry_rejects_values_outside_the_tool_contract(self) -> None:
        registry = ToolRegistry()

        with self.assertRaisesRegex(ValueError, "must be a Tool"):
            registry.register(object())


if __name__ == "__main__":
    unittest.main()
