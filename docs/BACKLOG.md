# Backlog

Work top to bottom inside a day. Each task is **done** only when its acceptance check passes. Tick the box and add the commit hash in the same commit. IDs: X = infra, B = backend, U = UI, E = evals, S = submission. 👤 means Harshil has to act (accounts, keys, dashboards).

Design: [`architecture.md`](architecture.md). Expected numbers: [`../evals/scenarios.md`](../evals/scenarios.md).

## Thu Oct 22: skeleton live

- [ ] **X-01** 👤 Commit the Day 1 work (Inngest, contract v0, tests) and this setup (demo-data, evals, docs, migration, CLAUDE.md) on `feature/setup`, then open a PR into `dev`. Diff `uv.lock` before committing. *Done when* `dev` contains everything and `uv run pytest` passes.
- [ ] **X-02** 👤 Create a Supabase project and run `supabase/migrations/0001_init.sql`. Put `DATABASE_URL` (transaction pooler, port 6543) in `.env`. *Done when* the tables are visible in the Supabase dashboard.
- [ ] **B-01** `backend/scripts/seed.py` loads `demo-data/` into `bank_transactions`, `gl_entries` and `balances` for dataset `northbrook-2026-10`. It is idempotent (upsert). Add `psycopg[binary,pool]` and use `prepare_threshold=None`. *Done when* re-running gives 112 / 114 / 1 rows.
- [ ] **X-03** Single-container image: a multi-stage Dockerfile at the repo root that builds `frontend/`, copies `dist/` into the backend image, and has FastAPI serve it at `/` with an SPA fallback. Keep `/health`, `/api/v1`, `/api/inngest` and `/docs`. Add `MODEL_NANO`, `MODEL_SUPER`, `MODEL_ULTRA` and `DATABASE_URL` to settings and `.env.example`. *Done when* `docker build -t bridge . && docker run -p 8000:8000 --env-file .env bridge` serves the UI and `/health` at :8000.
- [ ] **X-04** 👤 Deploy to a Nebius Serverless Endpoint (push the image to a registry Nebius can pull, set env secrets). Create an Inngest Cloud app, set `INNGEST_EVENT_KEY` and `INNGEST_SIGNING_KEY`, and sync `https://<endpoint>/api/inngest`. Use the `wizard` skill for the 👤 steps. *Done when* `bridge/smoke.requested` sent from Inngest Cloud completes all steps against the deployed URL. Record the URL in `docs/HANDOFF.md`.
- [ ] **U-01** UI foundation: `react-router`, `@tanstack/react-query`, `@tanstack/react-table`, and the shadcn components `table badge card sheet tabs progress skeleton sonner popover calendar select tooltip separator`. Add a sidebar layout with routes `/reconcile` (default), `/bank`, `/ledger`, `/runs/:id`, `/report/:runId`. `src/api/` holds a typed client per API v1 endpoint, plus a mock mode (`VITE_USE_MOCKS=true`) that serves `docs/fixtures/*.json`. *Done when* every route renders with mock data and `npm run build` passes.

## Fri Oct 23: rules, statement, read API, tables

- [ ] **B-02** Domain module `app/recon/`: `BankTxn`, `GlEntry`, `Item`, `ProposedEntry` and `Statement` models (amounts as `Decimal`), a repository over Supabase, and a loader that can also read `demo-data/` CSVs so tests run without a DB. *Done when* the unit tests load both sources the same way.
- [ ] **B-03** Rule-based matcher (TDD, `tdd` skill): exact match (amount, date window from policy), check number, one-to-many (subset sum of up to 4 GL lines within ±2 days), and rounding within tolerance. Ambiguous candidates are returned for fuzzy matching, never guessed. *Done when* every match it makes is correct against `ground_truth.json` (precision 1.0) and it covers 100 or more items.
- [ ] **B-04** Statement calculator: balances, deposits in transit, outstanding checks, book adjustments from approved and auto entries, and the unreconciled difference. *Done when* the tests reproduce a raw difference of 864.09, and 0.00 once all ground-truth resolutions are applied.
- [ ] **B-05** Read API v1: `GET /datasets`, `/bank-transactions`, `/gl-entries`, `/statement`. Replace the v0 schemas in `schemas/runs.py` and the fixtures with the v1 shapes from `architecture.md`, regenerate `docs/fixtures/`, and rewrite `docs/api-contract.md`. *Done when* the contract tests pass against the new fixtures.
- [ ] **E-01** `evals/run_eval.py`: run the pipeline on `demo-data/`, score it against `ground_truth.json` (match precision and recall, kind accuracy, correct escalations, false auto-resolutions, entry correctness, final difference), and write `evals/results/<timestamp>.json` plus a markdown table. *Done when* it scores the rules-only pipeline.
- [ ] **U-02** `TransactionTable` component: sorting, date-range filter, type and status filters, search, currency formatting with outflows in red, a sticky header, and row selection. Use it on `/bank` and `/ledger`. *Done when* both pages show real API data with filters working.
- [ ] **U-03** `StatusChip` (`matched`, `auto_resolved`, `reconciling_item`, `needs_approval`, `approved`, `rejected`, `unmatched`) and a static `StatementCard` that renders `GET /statement`. *Done when* it shows the bank and book sides and the 864.09 raw difference.

## Sat Oct 24: agents and workflow

- [ ] **B-06** LLM layer: a tier → model map from settings, JSON-mode helper with Pydantic parsing and up to 2 repair retries, timeouts, and per-call latency and token capture. Strip the leading newline from reasoning-model output. *Done when* a test calls the stub provider through every tier.
- [ ] **B-07** Spike, limited to 1 hour: does Super on Token Factory handle OpenAI `tools` reliably? Try 5 calls. Record the result in `architecture.md`, then pick native tools or the JSON action loop. *Done when* the decision is written down.
- [ ] **B-08** Guardrails: `app/guardrails/pii.py` and `injection.py`, per `architecture.md`. *Done when* tests show BANK004, BANK068 and BANK113 masked in the prompt text and BANK074 flagged, with the system prompt delimiting untrusted text.
- [ ] **B-09** Agents in `app/agents/`: `fuzzy_match` (Nano), `classify` (Nano), `resolve` (Super with tools), `review` (code checks plus Super critic, retry, then Ultra, then escalate), and `decide` (policy). Prompts live in `app/agents/prompts/*.md`. *Done when* E-01 on the full pipeline shows 0 false auto-resolutions and all 5 escalations with correct draft entries.
- [ ] **B-10** Inngest `reconcile-run` per `architecture.md`, with parallel steps for fuzzy match, classify and resolve, and `run_steps` rows updated live. Step outputs are IDs and counts only. Add `POST /runs`, `GET /runs/{id}` and `GET /runs/{id}/items`. Delete `workflows/smoke.py`. *Done when* a local run (Inngest dev server) completes and the DB holds the items.
- [ ] **B-11** `report` step (Ultra): a markdown narrative written from computed numbers only. *Done when* `GET /runs/{id}` returns the report and every number in it appears in the statement.

## Sun Oct 25: the hero flow

- [ ] **B-12** `POST /items/{id}/decision`, which emits `bridge/item.decided`. The `item-decided` function writes the audit log and saves a rule when `remember` is set. Add `POST /demo/reset`. *Done when* approving all 5 items makes `GET /statement` return 0.00.
- [ ] **U-04** Reconcile workspace: dataset and date range, a **Run agents** button, and bank and ledger side by side. Clicking an item highlights all of its rows on both sides.
- [ ] **U-05** Progress stepper: polls `GET /runs/{id}` every 1.5 s and shows each step's status, model tier badge, latency and output summary. Parallel steps appear side by side.
- [ ] **U-06** Approval drawer (Sheet): a card per `needs_approval` item with kind, amount, reasoning, clickable evidence, the draft entry as a DR/CR table, and Approve, Reject and Edit buttons plus a "Remember this rule" checkbox. Optimistic update with a toast.
- [ ] **U-07** A live `StatementCard` in the workspace. The difference animates (count-up) as items resolve and turns green at 0.00.
- [ ] **E-02** Full eval on the deployed models. Fix the top failures. *Done when* the result JSON is committed with false auto-resolutions at 0 and a final difference of 0.00.

## Mon Oct 26: Should items, deploy and hardening

- [ ] **B-13** Learning loop: `find_rules` is used in `resolve` and `decide`, and items resolved by a rule show "applied rule #N". *Done when* a second run auto-resolves the bank fee after a "remember" approval.
- [ ] **U-08** `/runs/:id` trace: a timeline of steps with model, latency and tokens, plus the audit log entries.
- [ ] **U-09** `/report/:runId`: renders the Ultra markdown report.
- [ ] **U-10** Guardrail callouts: an injection badge on BANK074, and a "sent to model" toggle showing the masked text on PII rows.
- [ ] **E-03** Tier comparison: the eval runs as `nano`, `super`, `tiered` and `ultra`, giving accuracy, latency and estimated cost. Show the chart in the UI (or the README). Keep the chart simple: one grouped bar per metric.
- [ ] **X-05** Deploy everything. Add loading, empty and error states with Retry. Add a demo reset button. *Done when* the full demo script in `evals/scenarios.md` runs on the deployed URL in a fresh incognito window.

## Tue Oct 27: freeze at noon, then package

- [ ] **S-01** README: what, why and how; an architecture diagram; the Nemotron models and where each tier is used; how Token Factory helped; the Nebius Serverless Endpoint; eval results; local setup; license badge.
- [ ] **S-02** Video script (follow the demo script in `evals/scenarios.md`, 3 minutes or less) and a first recording.
- [ ] **S-03** Go through the submission checklist in `PLAN.md`. Make the repo public. Draft the submission text.

## Stretch (only when Mon is done)

- [ ] **T-01** Upload a PDF bank statement; Nemotron Super VL (`nvidia/Nemotron-3.5-Super-VL`) extracts the rows.
- [ ] **T-02** Tavily lookup for `unidentified_receipt` and unknown payees.
- [ ] **T-03** pgvector: retrieve similar past approved resolutions as few-shot examples.
- [ ] **T-04** CSV and PDF export of the reconciliation report.
