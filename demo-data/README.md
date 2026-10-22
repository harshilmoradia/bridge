# Demo data: Northbrook Goods Co., Oct 1–10 2026

These are the inputs Bridge reconciles: one operating bank account against the cash account (1010) in the general ledger. All names, accounts and amounts are fictional.

| File | What it is |
|---|---|
| `bank_statement.csv` | 112 bank lines with a running balance. Columns: `txn_id, posted_date, description, amount, type, check_number, running_balance` |
| `gl_entries.csv` | 114 GL lines that touch account 1010. Columns: `entry_id, date, description, amount, method, check_number, account, counter_account, counterparty` |
| `balances.json` | Opening and closing balances for the bank and the GL, plus the period |
| `chart_of_accounts.csv` | Accounts the agents are allowed to use in draft entries |
| `policy.json` | Matching window, write-off tolerance, and which kinds of item auto-resolve or escalate |

**Sign convention:** positive means money came into the bank account, negative means money went out. The bank and GL use the same convention, so a matched pair has equal amounts.

**Answer key:** `../evals/ground_truth.json`. Only eval code reads it. Runtime code and prompts never do.

**Regenerate:** `python3 demo-data/generate.py`, run from the repo root. It reads `evals/source/` (the team's v1 spreadsheets exported to CSV) and gives the same output every time. `evals/scenarios.md` lists every change from v1 and the reason for it.

**Planted on purpose:** realistic bank descriptors (`ONLINE PMT TECHSOLNS INC CONF#780589`), PII in three memos, and a prompt-injection attempt in `BANK074`. The guardrails must handle all of these.
