# Bridge

An agentic bank reconciliation app for the Nebius x NVIDIA hackathon. Nemotron agents (via Nebius Token Factory) match a bank statement to the ledger, close what policy allows, and send the rest to a human with a draft journal entry. Build complete by **Tue Oct 27**; submit Thu Oct 29.

## Where things are

- `docs/BACKLOG.md`: **start here every session.** Pick the first unticked task for today. Its acceptance check is your completion criterion.
- `docs/architecture.md`: pipeline, model tiers, guardrails, DB, API v1, deploy. Read it before touching agents, the API or the schema.
- `docs/PLAN.md`: schedule, scope (Must, Should, Stretch) and cut order. Read it when deciding what to drop.
- `docs/HANDOFF.md`: current state and the latest decisions. Update it at the end of every session.
- `demo-data/`: agent inputs. `evals/`: the answer key, the demo script and the eval harness.
- `backend/` is FastAPI + Inngest (uv, Python 3.12). `frontend/` is Vite + React + Tailwind + shadcn. `supabase/migrations/` holds the schema.

## Commands

- Backend tests: `cd backend && uv run pytest`
- API dev server: `cd backend && INNGEST_DEV=1 uv run uvicorn app.main:app --reload`
- Inngest dev server: `npx inngest-cli@latest dev -u http://localhost:8000/api/inngest`
- Frontend: `cd frontend && npm run dev`, `npm run build`, `npm run lint`
- Regenerate demo data: `python3 demo-data/generate.py` (run from the repo root)
- Seed the DB (needs `DATABASE_URL`): `cd backend && uv run python -m scripts.seed`
- Single-container image: `docker build -t bridge . && docker run -p 8000:8000 --env-file backend/.env bridge` (UI and API on `$PORT`, default 8000)

## Rules

- **Answer key isolation:** `evals/ground_truth.json`, `evals/scenarios.md` and `evals/source/` are read only by eval code and tests. Runtime code and prompts load inputs from `demo-data/` or the DB.
- **Money:** `Decimal` in Python, decimal strings in JSON, `numeric(14,2)` in Postgres. Positive means money into the bank. All arithmetic happens in code, and the LLM receives computed numbers.
- **Gates:** auto-resolution depends on policy kind plus passing code checks. Model confidence is display-only.
- **Untrusted text:** bank and GL descriptions go through `app/guardrails` (PII masking, injection flagging) before any prompt, and sit inside `<untrusted>` tags.
- **Inngest step outputs** carry IDs and counts only, because Inngest Cloud stores them.
- **Secrets** stay in `backend/.env` (gitignored), the only backend env file. Read keys from settings and keep `.env.example` files key-free.
- **Contract changes:** edit `backend/app/schemas/` and `docs/fixtures/` together. `tests/test_run_contract.py` guards them.
- **Docker** runs on Harshil's Mac. Steps that need a dashboard or keys are marked 👤 in the backlog. Write a `wizard` skill script for them and let Harshil run it.
- **Git:** work on a feature branch off `dev`, in small slices. **Never commit before Harshil has reviewed the change:** stop with the diff summary and a test plan, and commit only when he says so. Use the task ID in the message (`B-03: rule-based matcher`). Push and open PRs when Harshil asks.
