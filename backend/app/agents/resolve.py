"""resolve (Super, native tools): explain one item and draft its fix.

Code gives the model the computed delta and, for kinds that need one, the exact entry
amount and which side cash goes on. The model picks the other account through
`propose_entry`, which runs the same code checks as review and only keeps an entry
that passes them. Row text reaches the model only through `prompt_row`.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, WithJsonSchema

from app.agents.checks import ENTRY_KINDS, entry_problems
from app.agents.context import CASH, Books
from app.agents.models import DraftEntry, WorkItem
from app.agents.prompts import system_prompt
from app.agents.rules import candidate_rules, direction
from app.core.errors import AppError
from app.guardrails import prompt_row
from app.llm import CallStats, LLMClient, Tier
from app.llm.tools import Tool, ToolStep
from app.schemas.chat import ChatMessage

MoneyArg = Annotated[Decimal, WithJsonSchema(
    {"type": "string", "pattern": r"^-?\d+\.\d{2}$", "description": "decimal string, e.g. 25.00"})]
SEARCH_LIMIT = 8


class SearchArgs(BaseModel):
    amount: MoneyArg | None = Field(default=None, description="exact signed amount")
    text: str | None = Field(default=None, description="case-insensitive substring of the description")


class KindArgs(BaseModel):
    kind: str


class AccountsArgs(BaseModel):
    type: Literal["asset", "liability", "income", "expense"] | None = None


class RuleArgs(BaseModel):
    description: str


class ProposeArgs(BaseModel):
    debit_account: str
    credit_account: str
    amount: MoneyArg
    memo: str = Field(max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1, description="display only")


@dataclass
class ResolveResult:
    explanation: str | None = None
    entry: DraftEntry | None = None
    confidence: float | None = None
    rejected: list[str] = field(default_factory=list)  # problems from the last refused proposal
    rule_ids: list[int] = field(default_factory=list)
    steps: tuple[ToolStep, ...] = ()
    stats: CallStats | None = None
    error: str | None = None


def entry_shape(item: WorkItem) -> dict[str, str]:
    return {"amount": str(abs(item.amount_delta)),
            "cash_side": "debit" if item.amount_delta > 0 else "credit",
            "cash_account": CASH}


def item_view(item: WorkItem, books: Books) -> dict:
    bank, gl = books.rows(item.bank_ids, item.gl_ids)
    return {
        "id": item.id,
        "kind": item.kind,
        "kind_policy": books.policy.resolution_for(item.kind),
        "bank_ids": list(item.bank_ids),
        "gl_ids": list(item.gl_ids),
        "bank": [prompt_row(b.model_dump()) for b in bank],
        "gl": [prompt_row(g.model_dump()) for g in gl],
        "amount_delta": str(item.amount_delta),
    }


def _tools(item: WorkItem, books: Books, result: ResolveResult) -> list[Tool]:
    def search(rows, date_attr):
        def run(args: SearchArgs) -> dict:
            hits = [r for r in rows
                    if (args.amount is None or r.amount == args.amount)
                    and (not args.text or args.text.lower() in r.description.lower())]
            return {"rows": [prompt_row(r.model_dump()) for r in hits[:SEARCH_LIMIT]],
                    "total": len(hits)}
        return run

    def get_policy(args: KindArgs) -> dict:
        p = books.policy
        return {"kind": args.kind, "resolution": p.resolution_for(args.kind),
                "auto_writeoff_tolerance": str(p.auto_writeoff_tolerance),
                "note": "Escalated items need a draft entry; nothing posts without approval."}

    def list_accounts(args: AccountsArgs) -> dict:
        return {"accounts": [a.model_dump() for a in books.accounts.values()
                             if args.type is None or a.type == args.type]}

    def find_rules(args: RuleArgs) -> dict:
        # The words alone are too broad ("ZELLE" covers receipts and payments): kind and direction too.
        text, way = args.description.lower(), direction(item.amount_delta)
        hits = [r for r in books.rules
                if r.pattern and r.pattern.lower() in text and r.kind == item.kind and r.direction == way]
        result.rule_ids = [r.id for r in hits]
        # No pattern: it came from untrusted row text. Ids and accounts are all the model needs.
        return {"rules": [{"id": r.id, "kind": r.kind,
                           "debit_account": r.debit_account, "credit_account": r.credit_account}
                          for r in hits]}

    def propose_entry(args: ProposeArgs) -> dict:
        entry = DraftEntry(debit_account=args.debit_account, credit_account=args.credit_account,
                           amount=args.amount, memo=args.memo)
        problems = entry_problems(item, entry, books)
        if problems:
            result.rejected = problems
            return {"accepted": False, "problems": problems}
        result.entry, result.confidence, result.rejected = entry, args.confidence, []
        return {"accepted": True}

    return [
        Tool("search_bank", "Search bank lines by exact amount and/or description text.",
             SearchArgs, search(books.dataset.bank, "posted_date")),
        Tool("search_gl", "Search GL cash lines by exact amount and/or description text.",
             SearchArgs, search(books.dataset.gl, "date")),
        Tool("get_policy", "Get the resolution policy for an item kind.", KindArgs, get_policy),
        Tool("list_accounts", "List the chart of accounts, optionally of one type.",
             AccountsArgs, list_accounts),
        Tool("find_rules", "Find learned rules for this item's kind and direction whose pattern appears "
             "in a description.",
             RuleArgs, find_rules),
        Tool("propose_entry", "Propose the draft journal entry. Code checks it and says whether "
             "it was accepted.", ProposeArgs, propose_entry),
    ]


async def resolve(
    client: LLMClient, tier: Tier, item: WorkItem, books: Books, feedback: list[str] = ()
) -> ResolveResult:
    result = ResolveResult()
    view = item_view(item, books)
    if item.kind in ENTRY_KINDS:
        view["required_entry"] = entry_shape(item)
    elif item.kind == "unknown":
        view["required_entry"] = None
        view["optional_entry"] = entry_shape(item)
    else:
        view["required_entry"] = None
    learned = candidate_rules(item, books)
    if learned:  # a human approved this pattern before: code says which accounts that entry used
        view["learned_rules"] = [{"id": r.id, "debit_account": r.debit_account,
                                  "credit_account": r.credit_account, "amount": str(r.amount)} for r in learned]
    body = {"item": view, "feedback": list(feedback)}
    messages = [ChatMessage(role="system", content=system_prompt("resolve")),
                ChatMessage(role="user", content=json.dumps(body))]
    try:
        run, stats = await client.complete_tools(tier, messages, _tools(item, books, result))
    except AppError as exc:  # timeout, upstream error: a failed attempt, not a crash
        result.error = exc.code
        return result
    result.explanation, result.steps, result.stats = run.text or None, run.steps, stats
    return result
