from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 500,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class LLMUnavailableError(AppError):
    def __init__(self, message: str = "LLM provider is unavailable") -> None:
        super().__init__(code="llm_unavailable", message=message, status_code=503)


class LLMUpstreamError(AppError):
    def __init__(self, message: str = "LLM upstream returned an unexpected response") -> None:
        super().__init__(code="llm_upstream_error", message=message, status_code=502)


def _error_body(code: str, message: str) -> dict[str, Any]:
    return {"detail": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message),
            headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=_error_body("internal_error", "An unexpected error occurred"),
        )
