"""Rule-based matcher: pairs bank lines with GL lines using code only, no LLM.

A pair is made only when each side is the other's single possible partner. Anything with
more than one valid partner comes back as a CandidateGroup for the fuzzy step.
"""

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from app.recon.loader import DATA_DIR
from app.recon.matching_models import (
    CandidateGroup,
    Match,
    MatchKind,
    MatchPolicy,
    MatchResult,
)
from app.recon.models import BankTxn, GlEntry

__all__ = ["MatchPolicy", "load_match_policy", "match"]

ZERO = Decimal("0.00")


def load_match_policy(data_dir: Path = DATA_DIR) -> MatchPolicy:
    raw = json.loads((data_dir / "policy.json").read_text(encoding="utf-8"), parse_float=Decimal)
    return MatchPolicy(
        date_window_days=raw["date_window_days"],
        rounding_tolerance=Decimal(raw["auto_writeoff_tolerance"]),
    )


def _gap(b: BankTxn, g: GlEntry) -> int:
    return abs((b.posted_date - g.date).days)


def _exact_kind(gap: int) -> MatchKind:
    return "exact" if gap == 0 else "timing"


def _make(kind: MatchKind, b: BankTxn, gls: Sequence[GlEntry]) -> Match:
    return Match(
        kind=kind,
        bank_ids=(b.txn_id,),
        gl_ids=tuple(g.entry_id for g in gls),
        amount_delta=b.amount - sum((g.amount for g in gls), start=ZERO),
        date_gap_days=max(_gap(b, g) for g in gls),
    )


def _exact_ok(b: BankTxn, g: GlEntry, window: int) -> bool:
    # A numbered check is identified by its number, so it never pairs on amount alone.
    no_checks = b.check_number is None and g.check_number is None
    return no_checks and b.amount == g.amount and _gap(b, g) <= window


def _check_ok(b: BankTxn, g: GlEntry) -> bool:
    # Number plus amount identifies the check, so no date window: checks clear late.
    return b.check_number is not None and b.check_number == g.check_number and b.amount == g.amount


class _Open:
    """Rows not yet matched, in input order."""

    def __init__(self, bank: Sequence[BankTxn], gl: Sequence[GlEntry]) -> None:
        self.bank = list(bank)
        self.gl = list(gl)
        self.matches: list[Match] = []

    def take(self, m: Match) -> None:
        self.matches.append(m)
        self.bank = [b for b in self.bank if b.txn_id not in m.bank_ids]
        self.gl = [g for g in self.gl if g.entry_id not in m.gl_ids]


def _unique_pairs(state: _Open, ok) -> list[tuple[BankTxn, GlEntry]]:
    """Pairs where the bank line has exactly one partner and that partner has exactly one."""
    found = []
    for b in state.bank:
        cands = [g for g in state.gl if ok(b, g)]
        if len(cands) == 1 and sum(1 for x in state.bank if ok(x, cands[0])) == 1:
            found.append((b, cands[0]))
    return found


def _exact_pass(state: _Open, policy: MatchPolicy) -> None:
    """Widen the window one day at a time, so a same-day partner wins over one days away.

    At each width a pair is taken only if it is unique on both sides at that width.
    Taking a pair can make another one unique, so each width repeats until nothing moves.
    """
    for window in range(policy.date_window_days + 1):
        while found := _unique_pairs(state, lambda b, g, w=window: _exact_ok(b, g, w)):
            for b, g in found:
                state.take(_make(_exact_kind(_gap(b, g)), b, [g]))


def _check_pass(state: _Open) -> None:
    for b, g in _unique_pairs(state, _check_ok):
        state.take(_make("check_number", b, [g]))


def _pair_options(state: _Open, policy: MatchPolicy) -> list[Match]:
    """One-to-one matches still open after the passes: each one had a rival."""
    window = policy.date_window_days
    options: list[Match] = []
    for b in state.bank:
        for g in state.gl:
            if _check_ok(b, g):
                options.append(_make("check_number", b, [g]))
            elif _exact_ok(b, g, window):
                options.append(_make(_exact_kind(_gap(b, g)), b, [g]))
    return options


def _sum_paths(amounts: list[Decimal], target: Decimal, max_lines: int) -> list[tuple[int, ...]]:
    """Index sets of 2 to `max_lines` amounts that sum to `target`. All values are positive
    and sorted ascending, so a branch stops once it overshoots or can no longer reach."""
    found: list[tuple[int, ...]] = []
    largest = amounts[-1] if amounts else ZERO

    def walk(start: int, chosen: tuple[int, ...], total: Decimal) -> None:
        slots = max_lines - len(chosen)
        for i in range(start, len(amounts)):
            running = total + amounts[i]
            if running > target:
                break
            if running + (slots - 1) * largest < target:
                continue
            picked = (*chosen, i)
            if running == target:
                if len(picked) >= 2:
                    found.append(picked)
            elif slots > 1:
                walk(i + 1, picked, running)

    walk(0, (), ZERO)
    return found


def _subset_options(state: _Open, policy: MatchPolicy, locked: set[str]) -> list[Match]:
    """Bank lines equal to the sum of 2 to N same-sign GL lines dated within the short window.

    Rows already in a one-to-one option are skipped: they have a simpler explanation."""
    options: list[Match] = []
    order = {g.entry_id: n for n, g in enumerate(state.gl)}
    for b in state.bank:
        if b.check_number is not None or b.txn_id in locked or b.amount == ZERO:
            continue
        target = abs(b.amount)
        pool = sorted(
            (
                g
                for g in state.gl
                if g.check_number is None
                and g.entry_id not in locked
                and g.amount != ZERO
                and (g.amount > ZERO) == (b.amount > ZERO)
                and abs(g.amount) <= target
                and _gap(b, g) <= policy.one_to_many_window_days
            ),
            key=lambda g: abs(g.amount),
        )
        amounts = [abs(g.amount) for g in pool]
        for path in _sum_paths(amounts, target, policy.one_to_many_max_lines):
            combo = sorted((pool[i] for i in path), key=lambda g: order[g.entry_id])
            options.append(_make("one_to_many", b, combo))
    return options


def _one_to_many_pass(state: _Open, options: list[Match]) -> list[Match]:
    """Take a subset only when no other subset shares its bank line or any of its GL lines.
    Returns the subsets left open; they all have a rival."""
    left: list[Match] = []
    for opt in options:
        rivals = [
            o
            for o in options
            if o is not opt and (o.bank_ids == opt.bank_ids or set(o.gl_ids) & set(opt.gl_ids))
        ]
        if rivals:
            left.append(opt)
        else:
            state.take(opt)
    return left


def _rounding_ok(b: BankTxn, g: GlEntry, policy: MatchPolicy, locked: set[str]) -> bool:
    delta = abs(b.amount - g.amount)
    return (
        b.txn_id not in locked
        and g.entry_id not in locked
        and b.check_number == g.check_number
        and (b.amount > ZERO) == (g.amount > ZERO)
        and ZERO < delta <= policy.rounding_tolerance
        and _gap(b, g) <= policy.date_window_days
    )


def _rounding_options(state: _Open, policy: MatchPolicy, locked: set[str]) -> list[Match]:
    return [
        _make("rounding", b, [g])
        for b in state.bank
        for g in state.gl
        if _rounding_ok(b, g, policy, locked)
    ]


def _rounding_pass(state: _Open, policy: MatchPolicy, locked: set[str]) -> None:
    # Runs last, and skips rows with an exact or one-to-many option: equal amounts win.
    for b, g in _unique_pairs(state, lambda b, g: _rounding_ok(b, g, policy, locked)):
        state.take(_make("rounding", b, [g]))


def _ids(options: list[Match]) -> set[str]:
    return {i for o in options for i in (*o.bank_ids, *o.gl_ids)}


def _group(options: list[Match], bank_order: list[str], gl_order: list[str]) -> list[CandidateGroup]:
    """Connected components of the options graph, so each group can be decided on its own."""
    groups: list[tuple[set[str], set[str], list[Match]]] = []
    for opt in options:
        bs, gs = set(opt.bank_ids), set(opt.gl_ids)
        hit = [grp for grp in groups if grp[0] & bs or grp[1] & gs]
        for grp in hit:
            groups.remove(grp)
            bs |= grp[0]
            gs |= grp[1]
        groups.append((bs, gs, [o for grp in hit for o in grp[2]] + [opt]))
    return [
        CandidateGroup(
            bank_ids=tuple(i for i in bank_order if i in bs),
            gl_ids=tuple(i for i in gl_order if i in gs),
            options=tuple(opts),
        )
        for bs, gs, opts in groups
    ]


def match(bank: Sequence[BankTxn], gl: Sequence[GlEntry], policy: MatchPolicy) -> MatchResult:
    state = _Open(bank, gl)
    _check_pass(state)
    _exact_pass(state, policy)
    # Pair and subset options are computed once: later passes only take rows outside them.
    pair = _pair_options(state, policy)
    subsets = _one_to_many_pass(state, _subset_options(state, policy, _ids(pair)))
    locked = _ids(pair + subsets)
    _rounding_pass(state, policy, locked)

    bank_order = [b.txn_id for b in state.bank]
    gl_order = [g.entry_id for g in state.gl]
    options = pair + subsets + _rounding_options(state, policy, locked)
    candidates = _group(options, bank_order, gl_order)
    in_bank = {i for c in candidates for i in c.bank_ids}
    in_gl = {i for c in candidates for i in c.gl_ids}
    return MatchResult(
        matches=tuple(state.matches),
        candidates=tuple(candidates),
        unmatched_bank_ids=tuple(i for i in bank_order if i not in in_bank),
        unmatched_gl_ids=tuple(i for i in gl_order if i not in in_gl),
    )
