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
