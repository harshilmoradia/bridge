# Bridge Backend

AI-ready FastAPI service for the Bridge project.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
cd backend
cp .env.example .env
uv sync
```

Default `LLM_PROVIDER=stub` so the API runs without an LLM API key.

For a real OpenAI-compatible provider, set in `.env`:

```bash
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000
```

- Health: http://localhost:8000/health
- OpenAPI: http://localhost:8000/docs

## Frontend

Point the Vite React app at this API with `frontend/.env.local`:

```bash
VITE_API_URL=http://localhost:8000
```

## Test

```bash
uv run pytest
```

## Supabase accounts

Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in `.env` and apply the profiles migration using [the setup guide](../docs/supabase-setup.md). A publishable or legacy anon key is sufficient; administrative keys are not used.

`GET /api/v1/auth/me`, `PATCH /api/v1/profile` and `POST /api/v1/chat` require `Authorization: Bearer <user-access-token>`. The server verifies each token with Supabase Auth, requires a confirmed email account, and queries PostgREST using the caller's JWT to preserve RLS. Missing/invalid credentials return 401; unconfigured or unreachable account services return 503. `/health` remains public.

`POST /api/v1/chat/ask` is the read-only RAG endpoint. It searches the selected dataset using exact, PostgreSQL full-text, and pgvector similarity ranking, then returns an answer plus server-verified source cards. It rejects system-role conversation history, screens questions and retrieved text with the existing guardrails, and never approves or changes records. With `PUBLIC_DEMO_API=true` (the local default), it works without login using the same anonymous demo identity as other demo APIs. Set `PUBLIC_DEMO_API=false` to require a confirmed-user bearer token. The legacy `POST /api/v1/chat` remains protected. With `DATABASE_URL` unset, search uses the configured demo CSV and in-memory runs; with Supabase connected, apply `supabase/migrations/20261030000000_rag_search_index.sql` after the existing migrations. Set `RAG_EMBEDDING_API_KEY` to enable Nebius vectors; if unset, or if the provider is unavailable, lexical search remains available. Only screened/masked text is sent to embedding or answer models.

Profile updates accept only `display_name` (1–100 characters). Authentication tests cover invalid tokens, profile isolation, forbidden update fields, upstream failures and the protected chat route. Signup, email confirmation and password recovery use the frontend's Supabase SDK rather than passing passwords through this backend.
