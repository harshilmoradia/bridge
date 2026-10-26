from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Paths owned by the backend: each name and everything under it. Unknown paths here
# return a JSON 404, not the SPA. Matching is per segment, so /healthcheck stays a client route.
BACKEND_PATHS = ("api", "health", "docs", "redoc", "openapi.json")
# Build output. A missing file here is a 404, never index.html served as JavaScript.
ASSET_DIR = "assets"


def _is_under(path: str, names: tuple[str, ...]) -> bool:
    return any(path == name or path.startswith(f"{name}/") for name in names)


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
        # "//assets/x" reaches here as "/assets/x"; strip so the checks below see "assets/x".
        path = path.lstrip("/")
        if _is_under(path, BACKEND_PATHS):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        if _is_under(path, (ASSET_DIR,)):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
