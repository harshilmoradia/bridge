# FastAPI AI-Ready Backend Scaffold Design

**Date:** 2026-10-06  
**Status:** Approved  
**Scope:** `backend/` AI-ready FastAPI skeleton (approach B)

## Intent

Build a FastAPI Python service for an LLM/AI product beside a Vite + React frontend. This scaffold establishes provider abstraction, async request flow, and clean API contracts. Database, auth, RAG, and streaming are deferred.

## Architecture

```text
Vite React (:5173) --HTTP/JSON--> FastAPI (:8000)
                                      |
                                 ChatService
                                      |
                              LLMProvider (Protocol)
                                   /        \
                          OpenAICompatible   Stub
```

### Layout

```text
backend/
  pyproject.toml
  README.md
  .env.example
  app/
    main.py
    core/{config,logging,errors}.py
    api/{router,deps}.py
    api/routes/{health,chat}.py
    schemas/{health,chat}.py
    services/chat.py
    providers/{base,stub,openai_compatible}.py
  tests/
```

### Principles

- Async end-to-end (routes → service → provider)
- Routers stay thin; orchestration in services; model I/O in providers
- Settings via env only; secrets never committed
- No DB/auth/vector store in this scaffold

## Configuration

Per-app env files:

| Location | Purpose |
|---|---|
| `backend/.env` | Server secrets and LLM settings |
| `frontend/.env.local` | `VITE_API_URL=http://localhost:8000` |

Backend variables: `APP_NAME`, `ENVIRONMENT`, `CORS_ORIGINS` (default `http://localhost:5173`), `LLM_PROVIDER` (`stub` \| `openai_compatible`), `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`.

Default local provider is `stub` so the app boots without an API key.

## API

### `GET /health`

```json
{ "status": "ok" }
```

### `POST /api/v1/chat`

Request:

```json
{
  "messages": [{ "role": "user", "content": "..." }],
  "model": null
}
```

Response:

```json
{
  "message": { "role": "assistant", "content": "..." },
  "model": "..."
}
```

Streaming (`text/event-stream`) is deferred; provider/service shape should allow adding it later without a rewrite.

## Errors

App errors return:

```json
{ "detail": { "code": "llm_unavailable", "message": "..." } }
```

| Status | When |
|---|---|
| 422 | Validation (FastAPI default) |
| 503 | Provider misconfigured / upstream unavailable |
| 502 | Unexpected upstream response |
| 500 | Unhandled (safe message, no stack traces to clients) |

## Logging

Stdlib logging with level, logger name, and message. Do not log API keys or full prompt bodies in production.

## Testing

pytest + httpx `AsyncClient`:

- `GET /health` → 200
- stub chat → 200
- empty messages → 422
- `openai_compatible` without key → 503

## Tooling

- Python 3.12+
- `uv` + `pyproject.toml`
- Dev: `uv run uvicorn app.main:app --reload --port 8000`
- OpenAPI at `/docs`

## Out of scope

Database, auth, RAG/vector store, streaming SSE, frontend API client wiring (only document `VITE_API_URL`).
