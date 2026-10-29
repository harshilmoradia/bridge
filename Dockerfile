# Single container: FastAPI serves the API, Inngest and the built UI on $PORT (default 8000).
#   docker build -t bridge . && docker run -p 8000:8000 --env-file backend/.env bridge

# --- frontend build ---
FROM node:22-bookworm-slim AS frontend

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Empty = same-origin: the UI calls /api on the host that served it.
ENV VITE_API_URL=
RUN npm run build

# --- backend runtime ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
COPY demo-data /demo-data
RUN uv sync --frozen --no-dev

COPY --from=frontend /frontend/dist ./static

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Hosts like Railway assign $PORT; exec keeps uvicorn as PID 1 so it receives SIGTERM.
CMD ["sh", "-c", "exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
