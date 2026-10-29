"""System prompts as markdown. Every prompt that carries row text gets the untrusted-data rules."""

from functools import cache
from pathlib import Path

from app.guardrails import with_untrusted_rules

_DIR = Path(__file__).parent


@cache
def system_prompt(name: str) -> str:
    return with_untrusted_rules((_DIR / f"{name}.md").read_text(encoding="utf-8"))
