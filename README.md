# bridge

> The AI bridge between your bank and your books. Powered by NVIDIA Nemotron on Nebius.

[License: Apache-2.0](LICENSE)

## What it does

Bridge is an agentic bank reconciliation app. Nemotron agents match a bank statement to the general ledger, close the items that policy allows, and send everything else to a human with a draft journal entry, its evidence and its reasoning.

The demo company is Northbrook Goods Co.: 112 bank lines and 114 GL lines for Oct 1–10 2026, with a planted transposition, a duplicate GL entry, bank fees and interest, NSF items, outstanding checks, PII in memos and a prompt-injection attempt.

## How it works

1. **Load:** bank and GL rows come from `demo-data/` (or Postgres).
2. **Guard (code):** PII is masked and injection attempts are flagged before any text reaches a model.
3. **Match:** code rules match first. Nemotron Nano picks fuzzy matches and classifies what's left.
4. **Resolve:** Nemotron Super (Ultra for hard cases) drafts a journal entry for each exception, and a critic reviews it.
5. **Decide (code):** an item auto-resolves only when policy allows its kind and every code check passes. Model confidence is shown, never used as a gate. Everything else goes to the approval inbox.
6. **Report:** Ultra writes a summary from facts computed in code, and a number checker verifies it.

Approving an item can teach a rule, so the next run resolves the same pattern on its own. The whole pipeline is an Inngest function, so each stage shows live progress in the UI.

## Run it locally

You can run Bridge without any accounts or keys. With the defaults, the backend reads `demo-data/`, keeps runs in memory, and uses a stub LLM: every code stage runs for real, and model stages fall back to code. Add a Nebius Token Factory key to see the Nemotron agents (step 4).

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) for option A, or Python 3.12 + [uv](https://docs.astral.sh/uv/) for option B
- Node.js 22+ (for `npx` and the frontend)

### Option A: one container (quickest)

```bash
git clone https://github.com/harshilmoradia/bridge
cd bridge
cp backend/.env.example backend/.env

# Terminal 1: the Inngest dev server (runs the workflow; dashboard at http://localhost:8288)
npx inngest-cli@latest dev -u http://localhost:8000/api/inngest --no-discovery

# Terminal 2: UI + API on one port
docker build -t bridge .
docker run --rm -p 8000:8000 --env-file backend/.env \
  -e INNGEST_DEV=http://host.docker.internal:8288 bridge
```

Open http://localhost:8000. The first build takes a few minutes.

There's no separate frontend step: the image builds the React UI and serves it from the same port as the API.

On Linux, add `--add-host=host.docker.internal:host-gateway` to `docker run`.

### Option B: from source (hot reload)

```bash
git clone https://github.com/harshilmoradia/bridge
cd bridge
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local

# Terminal 1: API on :8000
cd backend && uv sync && uv run uvicorn app.main:app --reload

# Terminal 2: Inngest dev server on :8288
npx inngest-cli@latest dev -u http://localhost:8000/api/inngest --no-discovery

# Terminal 3: UI on :5173
cd frontend && npm ci && npm run dev
```

Open http://localhost:5173.

### Try the demo

1. The app opens straight into the demo workspace. No sign-in is needed.
2. Click **Run agents** on the Reconcile page. Each stage shows its progress as it runs: load, guard, match, classify, resolve, review, decide and report. The run also appears in the Inngest dashboard at http://localhost:8288.
3. Open the items that need approval. Each one shows the matched rows, the draft journal entry, and the agent's reasoning. Approve, reject or edit it.
4. Approve them all and watch the unexplained difference go to 0.00.
5. Approve an item with **remember** checked to teach a rule, then run again: that item shows "Applied rule #N" and resolves without you.
6. Look at the run trace and audit timeline, the report, and the **Model tiers** eval page.
7. **Reset demo** clears runs and learned rules.

### Use real Nemotron models

Get an API key from [Nebius Token Factory](https://tokenfactory.nebius.com/), then set in `backend/.env`:

```bash
LLM_PROVIDER=openai_compatible
LLM_API_KEY=<your key>
```

Restart the API (or the container). A run then takes about 45–60 s, and each stage shows its model tier, latency and tokens.

### Check the API from the terminal

```bash
curl -s localhost:8000/health
ID=$(curl -s -X POST localhost:8000/api/v1/runs -H 'Content-Type: application/json' \
  -d '{"dataset":"northbrook-2026-10","period_start":"2026-10-01","period_end":"2026-10-10"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
curl -s localhost:8000/api/v1/runs/$ID          # status: queued -> running -> completed
curl -s "localhost:8000/api/v1/runs/$ID/items?status=needs_approval"
```

OpenAPI docs are at http://localhost:8000/docs. A run that stays `queued` means the Inngest dev server isn't running or can't reach the API.

## Tests and evals

```bash
cd backend && uv run pytest              # needs no keys: forces the stub LLM, skips DB tests without DATABASE_URL
cd frontend && npm test && npm run lint && npm run build

# Score a pipeline against the answer key (evals/ground_truth.json), from the repo root
uv run --project backend python -m evals.run_eval --pipeline models_off   # offline, no key
uv run --project backend python -m evals.run_eval --pipeline tiered       # needs LLM_API_KEY
```

Pipelines: `rules`, `models_off`, `nano`, `super`, `ultra`, `tiered`. Results are written to `evals/results/`.

## Optional: Postgres and sign-in

Without `DATABASE_URL`, runs live in memory and disappear on restart. To persist them in Supabase:

1. Create a Supabase project and run `supabase/migrations/*.sql` in the SQL editor, in filename order.
2. Set `DATABASE_URL` in `backend/.env` to the **transaction pooler** URI (port 6543).
3. Load the demo data: `cd backend && uv run python -m scripts.seed`.

Email/password sign-in is optional too: set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in `backend/.env`, and `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `frontend/.env.local`. Without them the UI opens the demo workspace.

## Environment files

| File | Used by | Notes |
|---|---|---|
| `backend/.env` | uvicorn, scripts, `docker run --env-file` | The only file with secrets. Every default runs offline. |
| `frontend/.env.local` | `npm run dev` / `npm run build` | API origin, mock mode, optional Supabase. |
| `.env` (repo root) | `docker compose` only | Build args and ports for the older two-container stack. |

## Repo layout

```
backend/      FastAPI + Inngest: agents, guardrails, recon logic, API v1
frontend/     Vite + React + Tailwind + shadcn
demo-data/    the agents' inputs (bank statement, GL, balances, policy, chart of accounts)
evals/        answer key, scoring and the eval harness
supabase/     database migrations
Dockerfile    single container: UI + API + Inngest endpoint on $PORT
render.yaml   Render deploy (prod and dev services)
```

## License

Apache-2.0
