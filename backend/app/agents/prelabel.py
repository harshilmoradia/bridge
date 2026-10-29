"""Code pre-labels: leftover rows whose kind code can prove, with a code-built draft entry.

Runs before classify, so Nano only sees the rows that need judgment. A label is given only when
the signal is structural and unambiguous: the bank's own transaction type with a sign that fits,
a check number that cleared once but was booked twice, a GL check that never cleared, a deposit
on the last days of the period, or one bank and one GL line with swapped digits and no other
candidate. Descriptions are never read here (they are untrusted text).

Every label is confirmed by `kind_problem`, and every draft by `entry_problems`, the same checks
review uses, so a pre-label is never weaker than a reviewed model label. Pre-labelled items still
go through resolve (Super explains them, and its entry wins if it passes the checks), the critic
and decide; the code draft is the fallback when the model cannot produce a passing one.
"""

from app.agents.checks import ENTRY_KINDS, entry_problems, kind_problem
from app.agents.context import CASH, Books
from app.agents.models import DraftEntry, WorkItem

# GL-only kinds code can prove, tried in this order. Duplicate first: an identical copy of a
# matched check also looks like an uncleared check.
PROVABLE_GL_KINDS = ("duplicate_gl_entry", "outstanding_check", "deposit_in_transit")
# Bank-only kinds proved by the bank's transaction type and sign (see `kind_problem`).
PROVABLE_BANK_KINDS = ("bank_fee_missing_in_gl", "interest_missing_in_gl")
# The counter account for a bank-only kind: the one chart account of that type whose name says so.
_COUNTER_BY_NAME = {"bank_fee_missing_in_gl": ("expense", "bank fee"),
                    "interest_missing_in_gl": ("income", "interest"),
                   "unidentified_receipt": ("liability", "suspense")}


def item_id(bank_ids, gl_ids) -> str:
    return "I-" + (tuple(bank_ids) + tuple(gl_ids))[0]


def work_item(books: Books, bank_ids, gl_ids, kind: str, source: str = "classify",
              draft: DraftEntry | None = None) -> WorkItem:
    return WorkItem(id=item_id(bank_ids, gl_ids), kind=kind, source=source,
                    bank_ids=tuple(bank_ids), gl_ids=tuple(gl_ids),
                    amount_delta=books.delta(bank_ids, gl_ids), draft=draft)


def _counter_account(item: WorkItem, books: Books) -> str | None:
    if item.kind in ("duplicate_gl_entry", "transposition"):
        return books.gl[item.gl_ids[0]].counter_account  # the fix reverses the original posting
    acct_type, name = _COUNTER_BY_NAME.get(item.kind, (None, None))
    hits = [a.account for a in books.accounts.values() if a.type == acct_type and name in a.name.lower()]
    return hits[0] if len(hits) == 1 else None


_MEMO = {
    "bank_fee_missing_in_gl": "Record bank fee {ids}",
    "interest_missing_in_gl": "Record bank interest {ids}",
    "duplicate_gl_entry": "Reverse duplicate entry {ids}",
    "transposition": "Correct transposed amount {ids}",
    "unidentified_receipt": "Hold unidentified receipt {ids} in suspense",
}


def code_draft(item: WorkItem, books: Books) -> DraftEntry | None:
    """The entry that closes the item: cash on the side the delta says, the kind's counter account.
    None if the kind takes no entry, or no single counter account fits, or the checks refuse it."""
    if item.kind not in ENTRY_KINDS or item.kind not in _MEMO:
        return None
    other = _counter_account(item, books)
    if other is None:
        return None
    delta = item.amount_delta
    draft = DraftEntry(debit_account=CASH if delta > 0 else other, credit_account=other if delta > 0 else CASH,
                       amount=abs(delta), memo=_MEMO[item.kind].format(ids=", ".join(item.bank_ids + item.gl_ids)))
    return draft if not entry_problems(item, draft, books) else None


def _proven(books: Books, bank_ids, gl_ids, kind: str) -> WorkItem | None:
    """The item if code proves the kind and, for an entry kind, can build its draft."""
    work = work_item(books, bank_ids, gl_ids, kind, source="code")
    if kind_problem(work, books) is not None:
        return None
    if kind in ENTRY_KINDS:
        draft = code_draft(work, books)
        return None if draft is None else work.model_copy(update={"draft": draft})
    return work


def _transpositions(books: Books, bank_ids: list[str], gl_ids: list[str]) -> list[WorkItem]:
    """Bank/GL pairs with swapped digits, close in date, where each row has exactly one partner."""
    window = books.policy.date_window_days
    pairs = []
    for b in bank_ids:
        for g in gl_ids:
            if abs((books.bank[b].posted_date - books.gl[g].date).days) > window:
                continue
            if (work := _proven(books, [b], [g], "transposition")) is not None:
                pairs.append(work)
    per_bank = [w.bank_ids[0] for w in pairs]
    per_gl = [w.gl_ids[0] for w in pairs]
    return [w for w in pairs if per_bank.count(w.bank_ids[0]) == 1 and per_gl.count(w.gl_ids[0]) == 1]


def prelabel(books: Books, bank_ids: list[str], gl_ids: list[str]) -> tuple[list[WorkItem], list[str], list[str]]:
    """Label the leftover rows code can prove; return (items, the bank rest, the GL rest)."""
    items = _transpositions(books, bank_ids, gl_ids)
    used = {i for w in items for i in w.bank_ids + w.gl_ids}
    rest_bank: list[str] = []
    rest_gl: list[str] = []
    for bid in bank_ids:
        if bid in used:
            continue
        work = next((w for k in PROVABLE_BANK_KINDS if (w := _proven(books, [bid], [], k))), None)
        if work:
            items.append(work)
        else:
            rest_bank.append(bid)
    for gid in gl_ids:
        if gid in used:
            continue
        work = next((w for k in PROVABLE_GL_KINDS if (w := _proven(books, [], [gid], k))), None)
        if work:
            items.append(work)
        else:
            rest_gl.append(gid)
    return items, rest_bank, rest_gl


def backstop(books: Books, items: list[WorkItem], rest_gl: list[str]) -> list[WorkItem]:
    """After classify. A model label that passes its check gets the code draft as its fallback. A
    lone bank credit the model gave up on (unknown, or a kind its rows disagree with) becomes an
    unidentified receipt held in suspense, but only when no leftover GL credit could explain it."""
    open_book_credit = any(books.gl[g].amount > 0 for g in rest_gl)
    out = []
    for w in items:
        if w.kind != "unknown" and kind_problem(w, books) is None:
            draft = code_draft(w, books) if w.kind in ENTRY_KINDS else None
            out.append(w.model_copy(update={"draft": draft}) if draft else w)
            continue
        lone_credit = len(w.bank_ids) == 1 and not w.gl_ids and w.amount_delta > 0
        held = None if open_book_credit or not lone_credit else _proven(books, w.bank_ids, [], "unidentified_receipt")
        out.append(held or w)
    return out


def code_reasoning(item: WorkItem, books: Books) -> str:
    """Why code labelled the item, in ids and computed numbers only."""
    ids = ", ".join(item.bank_ids + item.gl_ids)
    why = {
        "bank_fee_missing_in_gl": "the bank line's type is FEE and it takes money out, with no GL line",
        "interest_missing_in_gl": "the bank line's type is INTEREST and it pays money in, with no GL line",
        "duplicate_gl_entry": "a matched GL line has the same amount and check number or memo, and this "
                              "copy never reached the bank",
        "transposition": "the bank and GL amounts differ by two adjacent digits swapped",
        "unidentified_receipt": "a bank credit with no GL line, and no book line left that could explain "
                                "it, so it is held in suspense until someone identifies it",
        "outstanding_check": "a GL check payment in the period that has not cleared the bank",
        "deposit_in_transit": "a GL deposit at period end that the bank has not posted yet",
    }.get(item.kind, item.kind)
    who = "Labelled by code" if item.source == "code" else "Labelled by Nano; draft built by code"
    text = f"{who} ({ids}): {why}. Difference {item.amount_delta}."
    if item.draft:
        d = item.draft
        text += (f" Draft: DR {d.debit_account} {books.accounts[d.debit_account].name} / "
                 f"CR {d.credit_account} {books.accounts[d.credit_account].name}, {d.amount}.")
    return text

