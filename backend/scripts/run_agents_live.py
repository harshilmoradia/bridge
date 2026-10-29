"""Live pass of the B-09 agent pipeline on demo-data. Prints IDs, kinds, entries and stats only.

Run from backend/: `uv run python -m scripts.run_agents_live [path/to/.env]`.
"""

import asyncio
import sys
import time
from collections import Counter
from decimal import Decimal

from app.agents.pipeline import run_agents, total_entries
from app.core.config import Settings
from app.llm import get_llm_client
from app.recon.loader import load_dataset


async def main() -> None:
    s = Settings(_env_file=sys.argv[1] if len(sys.argv) > 1 else ".env")
    dataset = load_dataset(s.dataset)
    start = time.perf_counter()
    run = await run_agents(dataset, get_llm_client(s))
    wall = time.perf_counter() - start
    print(f"wall {wall:.1f}s, statuses {dict(Counter(i.status for i in run.items))}")
    for step in run.steps:
        print(f"  {step.id:12} {step.tier:5} calls={step.calls} {step.latency_ms}ms "
              f"in={step.tokens_in} out={step.tokens_out} | {step.summary}")
    for i in run.items:
        if i.status in ("matched",):
            continue
        e = i.entry
        entry = f"DR {e.debit_account} CR {e.credit_account} {e.amount}" if e else "-"
        print(f"{i.status:16} {i.kind:24} {'+'.join(i.bank_ids + i.gl_ids):16} "
              f"delta={i.amount_delta:>9} {entry:28} {i.model or ''} problems={i.problems}")
    fuzzy = [i for i in run.items if i.status == "matched" and i.reasoning
             and "Nano" in i.reasoning]
    print("fuzzy pairs:", [f"{'+'.join(i.bank_ids + i.gl_ids)}" for i in fuzzy])
    b = dataset.balances
    rec = sum((-sum(dataset.gl[[g.entry_id for g in dataset.gl].index(x)].amount
                    for x in i.gl_ids) for i in run.items if i.status == "reconciling_item"),
              Decimal("0.00"))
    print(f"adjusted bank {b.bank_closing_balance - rec} vs book after approvals "
          f"{b.gl_closing_balance + total_entries(run.items)}")


if __name__ == "__main__":
    asyncio.run(main())
