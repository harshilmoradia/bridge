from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Paths owned by the backend. Unknown paths under these return a JSON 404, not the SPA.
BACKEND_PREFIXES = ("api/", "health", "docs", "redoc", "openapi.json")


def mount_spa(app: FastAPI, static_dir: str) -> None:
    """Serve the built frontend at / with an index.html fallback for client routes.

    Register this last so every API route takes precedence.
    """
    root = Path(static_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith(BACKEND_PREFIXES):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
