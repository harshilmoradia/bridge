# bridge

> The AI bridge between your bank and your books. Powered by NVIDIA Nemotron on Nebius.

[License: Apache-2.0]

## What it does
Bridge is an AI accounting agent that works through the month instead of
waiting for month-end. It matches bank transactions to bills and invoices,
reconciles corporate card spend, and proposes accruals and prepaid
amortization. Every proposed entry includes its source document,
reasoning, and a confidence score. High-confidence items post
automatically, and the rest go to a human exception queue.

## Why
Month-end close is slow because manual work piles up. Most of it is
repetitive matching and coding that an agent can do as data arrives,
leaving accountants to review exceptions and explain the numbers.

## How it works
1. Bank, bill, invoice and card data comes in.
2. Nemotron models match and classify transactions, routed by difficulty.
3. Entries are proposed with evidence and confidence scores.
4. A human approves exceptions, and entries post to a mock ERP
   with a full audit trail.

## Quick start

```bash
git clone https://github.com/<you>/bridge
cd bridge
cp backend/.env.example backend/.env   # backend secrets: LLM key, DATABASE_URL
cp .env.example .env                   # frontend + Compose settings
docker build -t bridge . && docker run -p 8000:8000 --env-file backend/.env bridge
```

- UI, API and Inngest on one origin: http://localhost:8000 (honours `$PORT`, e.g. on Railway)

The older two-container stack still works with `docker compose up --build`:

- UI: http://localhost:8080
- Health (via nginx): http://localhost:8080/health
- API docs (via nginx): http://localhost:8080/docs

Default `LLM_PROVIDER=stub` so the stack runs without an API key.

Email/password authentication uses Supabase. Follow [the Supabase setup guide](docs/supabase-setup.md) to create a project, apply the profiles migration, and configure email redirects and environment variables. Without configuration, the UI offers sample demo access; the backend chat/account endpoints require real Supabase authentication. Reconciliation data remains a browser-local demo at this stage.

### Hot-reload development

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

- UI (Vite): http://localhost:5173
- API (direct): http://localhost:8000
- Health: http://localhost:8000/health

Backend env lives in `backend/.env` (see `backend/.env.example`). The repo-root `.env` holds only frontend and Compose settings.

## Repo layout

```
frontend/   backend/   docs/
docker-compose.yml
docker-compose.dev.yml
.env.example
```

## License
Apache-2.0
