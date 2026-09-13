"""Run one explicit, paid OpenAI provider smoke call for Step 1.8."""

from __future__ import annotations

import argparse
import json
import os

from app.agent import Message, MessageRole
from app.providers import OpenAIChatModel, OpenAIProviderError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate RepoPilot's OpenAI adapter with one real API call."
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("REPOPILOT_OPENAI_MODEL", ""),
        help="OpenAI model ID; defaults to REPOPILOT_OPENAI_MODEL.",
    )
    args = parser.parse_args()
    if not args.model.strip():
        parser.error("--model or REPOPILOT_OPENAI_MODEL is required")

    try:
        provider = OpenAIChatModel.from_env(model=args.model)
        response = provider.complete(
            (
                Message(
                    role=MessageRole.USER,
                    content=(
                        "Reply with exactly REPOPILOT_PROVIDER_OK and do not call tools."
                    ),
                ),
            ),
            [],
        )
    except (OpenAIProviderError, ValueError) as exc:
        print(f"OpenAI provider validation failed: {exc}")
        return 1

    print(
        json.dumps(
            {
                "model": provider.model,
                "role": response.role.value,
                "content": response.content,
                "tool_call_count": len(response.tool_calls),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
