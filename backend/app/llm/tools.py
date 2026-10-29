"""Native tool definitions for `LLMClient.complete_tools`.

A `Tool` pairs an OpenAI function spec (built from a Pydantic args model) with the code
that runs it. The model only chooses a tool and its arguments; code validates them and
does the work.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]]

    def spec(self) -> dict[str, Any]:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": schema}}


@dataclass(frozen=True)
class ToolStep:
    """One tool call in the trace: name and whether it ran. No arguments, so it is safe to store."""

    name: str
    ok: bool


@dataclass(frozen=True)
class ToolRun:
    text: str | None  # the model's final answer; None when the turn cap was hit first
    steps: tuple[ToolStep, ...]

    @property
    def exhausted(self) -> bool:
        return self.text is None
