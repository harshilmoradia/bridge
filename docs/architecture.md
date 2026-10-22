# Bridge architecture

Bridge reconciles a bank statement against the general ledger's cash account. The headline is a **reconciliation statement that closes to 0.00**. Agents close what policy allows. Everything else goes to a human with a reason, evidence and a draft journal entry.

## Principles

1. **Code first, then agents.** Deterministic code handles matching, sums, balances and policy. LLMs handle only what needs judgement: messy descriptions, classifying exceptions, explaining causes, drafting fixes and writing the report.
2. **The LLM never does arithmetic.** Every amount, delta and balance is computed in Python with `Decimal`, and the LLM gets the numbers it needs. Code re-checks every LLM claim.
3. **Gate on verifiable facts, not model confidence.** An item auto-resolves only if its kind is on the `policy.json` auto list, the code checks pass and the amounts tie. Self-reported confidence is shown in the UI and never used as a gate.
4. **Nothing posts without approval**, except rounding write-offs within tolerance.
5. **Untrusted text stays data.** Bank memos are delimited as data in prompts, scanned for injection, and redacted before any model call.

## Pipeline: Inngest function `reconcile-run`

Triggered by the event `bridge/run.requested {run_id, dataset, period_start, period_end}`. Each step writes a `run_steps` row, which the UI polls. **Step return values are IDs and counts only.** Inngest Cloud stores step outputs, so raw transaction text must never pass through them.

| # | Step | Who | What it does |
|---|---|---|---|
| 1 | `load` | code | Load the period's bank and GL rows from Supabase. Compute balances and the raw difference. |
| 2 | `guard` | code + Nano | Redact PII and scan memos for injection. Write any flags to `audit_log`. |
| 3 | `match-rules` | code | Exact (amount + date window), check number, one-to-many (subset sum of up to 4 GL lines within ±2 days), rounding within tolerance. |
| 4 | `match-fuzzy` | Nano, parallel batches | Ambiguous candidates (same amount, more than one possible partner): pick by description. Output is JSON with IDs from the candidate list only. |
| 5 | `classify` | Nano, parallel | Each leftover item gets a `kind` from the fixed enum in `policy.json`, or `unknown`. |
| 6 | `resolve` | Super, one per item, parallel | Tool-using agent. It explains the cause and drafts a fix (a balanced entry or a reconciling-item label). Tools: `search_bank`, `search_gl`, `get_policy`, `list_accounts`, `find_rules`, `propose_entry`. |
| 7 | `review` | code checks + Super critic | Code checks: the entry balances, accounts exist, cited IDs exist, the fix closes the item's delta, and the kind is consistent with policy. Super checks whether the explanation makes sense. On failure: retry `resolve` with the critic's feedback, then one retry on Ultra, then escalate as `unknown`. |
| 8 | `decide` | code | Apply policy: `auto_match`, `auto_match_with_writeoff`, `reconciling_item`, or `escalate`. Escalated items get `pending_approval`. |
| 9 | `report` | Ultra | Narrative reconciliation report written from numbers code has already computed. |

Approvals happen outside the run. `POST /items/{id}/decision` records the decision and emits `bridge/item.decided`. A small Inngest function `item-decided` writes the audit log and, when the reviewer ticks "remember", saves a rule. The statement is recomputed on read, so it reaches 0.00 as approvals land.

**Learning loop (Should):** when a rule exists for a pattern (for example, `MONTHLY SERVICE FEE` → 6800), `find_rules` returns it, and `decide` may auto-resolve that kind with "applied rule #N (approved by …)".

### Model tiers (Nemotron on Nebius Token Factory)

| Tier | Model id | Used for |
|---|---|---|
| Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Injection check, fuzzy match, classify |
| Super | `nvidia/nemotron-3-super-120b-a12b` | Resolve, critic |
| Ultra | `nvidia/Nemotron-3-Ultra-550b-a55b` | Report, last retry for hard items |

All three go through the existing `openai_compatible` provider. Model ids come from env (`MODEL_NANO`, `MODEL_SUPER`, `MODEL_ULTRA`). Reasoning models can return content with a leading newline, so strip it. Every call records the model, latency and tokens on its `run_steps` row.

**Tool calling is unverified.** If Token Factory's OpenAI-style `tools` is unreliable for Super, fall back to a JSON action loop: the model returns `{"action": "search_gl", "args": {...}}`, code executes it and appends the result, repeated up to 6 turns. Backlog B-07 decides which.

## Guardrails

- **PII redaction** (`app/guardrails/pii.py`) runs before any prompt is built. It masks account numbers to `****4417` style, and replaces emails, phone numbers, SSN patterns and individual names on known people-payee rows with placeholders. Business counterparty names are kept, because matching needs them. The UI shows original text from the DB and a "sent to model" view showing the masked version.
- **Injection** (`app/guardrails/injection.py`): regex heuristics, plus a Nano yes/no check on rows the heuristics flag. Flagged rows are still matched by code. Their text goes into prompts inside `<untrusted>` tags, and the system prompts state that instructions inside data are never followed.
- **Output validation:** every LLM output is parsed into a Pydantic model. Unknown IDs, unbalanced entries or accounts missing from the chart of accounts are rejected and trigger a retry.

## Data (Supabase Postgres)

Schema: `supabase/migrations/0001_init.sql`. RLS is on with no policies, so only the backend (direct DB connection or service role) can read and write. The browser never talks to Supabase.

`bank_transactions`, `gl_entries`, `balances`: loaded from `demo-data/` by `backend/scripts/seed.py`.
`runs`, `run_steps`: run state for the UI.
`items`: one row per reconciliation item (a match group or an exception), holding `kind`, `resolution`, `status`, `bank_ids[]`, `gl_ids[]`, `amount_delta`, `reasoning`, `evidence` and `model`.
`proposed_entries`: the draft journal entry for an item.
`decisions`: human approve or reject, with an optional edit and a `remember` flag.
`rules`: learned patterns.
`audit_log`: every agent and human action.

Connection: `DATABASE_URL` points at the Supabase **transaction pooler** (port 6543). Use `psycopg` 3 async with `prepare_threshold=None`. The pooler does not support prepared statements, and the serverless container must not hold long connections.

## API v1 (replaces the v0 contract in `api-contract.md`)

Base path `/api/v1`. Money is a decimal string. Errors look like `{"detail": {"code", "message"}}`.

| Method | Path | Returns |
|---|---|---|
| GET | `/datasets` | `[{id, label, period_start, period_end}]` (one dataset: `northbrook-2026-10`) |
| GET | `/bank-transactions?dataset&from&to` | Rows plus `recon_status` and `item_id` from the latest run |
| GET | `/gl-entries?dataset&from&to` | The same shape for GL rows |
| GET | `/statement?dataset&run_id` | The reconciliation statement: balances, reconciling items, adjustments, `unreconciled_difference` |
| POST | `/runs` | `{dataset, period_start, period_end}` → `202 {id, status}` |
| GET | `/runs/{id}` | The run with `steps[]` (`model`, `tier`, `latency_ms`, `tokens`), `counts`, and the `report` once done |
| GET | `/runs/{id}/items?status=` | Items with their `proposed_entry` and `evidence` |
| POST | `/items/{id}/decision` | `{decision: approve\|reject, entry_override?, remember, note}` → the updated item and statement |
| GET | `/rules` | Learned rules |
| POST | `/demo/reset` | Clears runs, items, decisions and rules for a clean demo |

Recon status values: `matched`, `auto_resolved`, `reconciling_item`, `needs_approval`, `approved`, `rejected`, `unmatched`.

## Deployment

- **One container** builds the frontend (`vite build`) and has FastAPI serve `frontend/dist` at `/`. The API is at `/api/v1` and Inngest at `/api/inngest`. One URL serves the demo, with no CORS in production.
- Hosted on a **Nebius Serverless Endpoint** (fallback: any container host, with Token Factory kept for inference). It needs a public HTTPS URL that Inngest Cloud can call.
- Secrets are endpoint env vars and never in the image: `LLM_API_KEY`, `DATABASE_URL`, `INNGEST_EVENT_KEY`, `INNGEST_SIGNING_KEY`, plus `ENVIRONMENT=production`.

## Evals

`evals/run_eval.py` runs the pipeline on `demo-data/` and scores it against `evals/ground_truth.json`: match precision and recall, item-kind accuracy, correct escalations, **false auto-resolutions (must be 0)**, draft-entry correctness, and the final difference. With `--tiers nano|super|tiered|ultra` it writes `evals/results/*.json` and a markdown table, which feed the "tiered vs single model" chart for the video.
