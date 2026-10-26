"""What the rule-based matcher returns. Money is Decimal; IDs only, so results stay small."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

MatchKind = Literal["exact", "timing", "check_number", "one_to_many", "rounding"]


class MatchPolicy(BaseModel):
    """The matching part of policy.json, plus the fixed one-to-many limits from architecture.md."""

    model_config = ConfigDict(frozen=True)

    date_window_days: int
    rounding_tolerance: Decimal
    one_to_many_window_days: int = 2
    one_to_many_max_lines: int = 4


class Match(BaseModel):
    """One bank line tied to one or more GL lines.

    `amount_delta` is bank total minus GL total: 0.00 except for `rounding`.
    `date_gap_days` is the largest gap between the bank date and any GL date.
    """

    model_config = ConfigDict(frozen=True)

    kind: MatchKind
    bank_ids: tuple[str, ...]
    gl_ids: tuple[str, ...]
    amount_delta: Decimal
    date_gap_days: int


class CandidateGroup(BaseModel):
    """Rows the rules could not pair uniquely. Every option is a valid match on its own;
    the fuzzy step picks among `options` and may not invent IDs outside them."""

    model_config = ConfigDict(frozen=True)

    bank_ids: tuple[str, ...]
    gl_ids: tuple[str, ...]
    options: tuple[Match, ...]


class MatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    matches: tuple[Match, ...]
    candidates: tuple[CandidateGroup, ...]
    unmatched_bank_ids: tuple[str, ...]
    unmatched_gl_ids: tuple[str, ...]
