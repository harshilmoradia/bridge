"""Code checks: the only gate besides policy kind. Model output never passes without them.

`kind_problem` checks that an item's rows fit its kind. `entry_problems` checks a draft
entry: accounts exist, one side is cash on the right side, the amount closes the item's
delta, and the counter account suits the kind. Each returns plain reasons (no row text).
"""

from decimal import Decimal

from app.agents.context import CASH, Books
from app.agents.models import DraftEntry, WorkItem

ZERO = Decimal("0.00")

# Kinds whose fix is a journal entry the reviewer approves.
ENTRY_KINDS = frozenset({
    "bank_fee_missing_in_gl", "interest_missing_in_gl", "duplicate_gl_entry",
    "transposition", "unidentified_receipt",
})


def _digits(amount: Decimal) -> str:
    return "".join(sorted(str(abs(amount)).replace(".", "")))


def kind_problem(item: WorkItem, books: Books) -> str | None:
    bank, gl = books.rows(item.bank_ids, item.gl_ids)
    shape = (len(bank), len(gl))
    k = item.kind
    if k == "unknown":
        return None
    if k == "nsf_pair":
        ok = shape == (1, 1) and bank[0].amount == gl[0].amount < 0 \
            and bank[0].type == "RETURNED_ITEM"
        return None if ok else "nsf_pair needs one returned-item bank line equal to one GL line"
    if k == "outstanding_check":
        ok = shape == (0, 1) and gl[0].amount < 0 and gl[0].check_number is not None \
            and gl[0].date <= books.period_end \
            and not any(b.check_number == gl[0].check_number for b in books.dataset.bank)
        return None if ok else \
            "outstanding_check needs one GL check payment in the period that has not cleared the bank"
    if k == "deposit_in_transit":
        ok = shape == (0, 1) and gl[0].amount > 0 and gl[0].method == "DEPOSIT" \
            and 0 <= (books.period_end - gl[0].date).days <= books.policy.date_window_days
        return None if ok else "deposit_in_transit needs one GL deposit near period end"
    if k == "bank_fee_missing_in_gl":
        ok = shape == (1, 0) and bank[0].amount < 0 and bank[0].type == "FEE"
        return None if ok else "bank_fee_missing_in_gl needs one bank FEE line with no GL line"
    if k == "interest_missing_in_gl":
        ok = shape == (1, 0) and bank[0].amount > 0 and bank[0].type == "INTEREST"
        return None if ok else "interest_missing_in_gl needs one bank INTEREST credit with no GL line"
    if k == "unidentified_receipt":
        ok = shape == (1, 0) and bank[0].amount > 0
        return None if ok else "unidentified_receipt needs one bank credit with no GL line"
    if k == "duplicate_gl_entry":
        if shape != (0, 1):
            return "duplicate_gl_entry needs one GL line"
        g = gl[0]
        twins = [
            o for o in books.dataset.gl
            if o.entry_id != g.entry_id and o.entry_id in books.matched_gl_ids
            and (o.amount, o.description, o.check_number, o.counterparty)
            == (g.amount, g.description, g.check_number, g.counterparty)
        ]
        return None if twins else "duplicate_gl_entry needs a matched GL line identical to it"
    if k == "transposition":
        ok = shape == (1, 1) and bank[0].amount != gl[0].amount \
            and (bank[0].amount < 0) == (gl[0].amount < 0) \
            and _digits(bank[0].amount) == _digits(gl[0].amount) \
            and (bank[0].amount - gl[0].amount) % 9 == 0
        return None if ok else "transposition needs one bank and one GL line with swapped digits"
    return f"{k} is not a kind classify may assign"


def entry_problems(item: WorkItem, entry: DraftEntry | None, books: Books) -> list[str]:
    kind = item.kind
    if entry is None:
        return ["an entry is required for this kind"] if kind in ENTRY_KINDS else []
    if kind not in ENTRY_KINDS and kind != "unknown":
        return [f"{kind} takes no journal entry"]
    problems: list[str] = []
    for acct in (entry.debit_account, entry.credit_account):
        if acct not in books.accounts:
            problems.append(f"account {acct} is not in the chart of accounts")
    delta = item.amount_delta
    if entry.amount != abs(delta) or entry.amount <= ZERO:
        problems.append(f"amount must be {abs(delta)} to close the item")
    cash_side = entry.debit_account if delta > ZERO else entry.credit_account
    other = entry.credit_account if delta > ZERO else entry.debit_account
    if cash_side != CASH or other == CASH:
        side = "debit" if delta > ZERO else "credit"
        problems.append(f"cash ({CASH}) must be the {side} side and only that side")
    if problems:
        return problems
    acct_type = books.accounts[other].type
    if kind == "bank_fee_missing_in_gl" and acct_type != "expense":
        problems.append("a bank fee posts to an expense account")
    if kind == "interest_missing_in_gl" and acct_type != "income":
        problems.append("interest posts to an income account")
    if kind == "unidentified_receipt" and acct_type != "liability":
        problems.append("an unidentified receipt is held in a liability (suspense) account until identified")
    if kind in ("duplicate_gl_entry", "transposition"):
        original = books.gl[item.gl_ids[0]].counter_account
        if other != original:
            problems.append(f"the fix must reverse the original counter account {original}")
    return problems
