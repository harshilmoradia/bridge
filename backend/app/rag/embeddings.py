"""Hosted text embeddings for Bridge's derived search index.

The adapter accepts only already-screened text. It intentionally logs no request or response body,
which may contain transaction descriptions or PII that escaped a detector.
"""

from collections.abc import Sequence
import logging
import math
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.errors import LLMUnavailableError, LLMUpstreamError

logger = logging.getLogger(__name__)
EMBEDDING_DIMENSIONS = 1536
NEBIUS_HOST = "api.tokenfactory.nebius.com"


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class NebiusEmbeddingProvider:
    """OpenAI-compatible Nebius `/embeddings` client using Qwen's 1,536-dimension output."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.model,
            "input": list(texts),
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError("Embedding request timed out", diagnostic_code="embedding_timeout") from exc
        except httpx.RequestError as exc:
            logger.warning("Embedding request failed: %s", type(exc).__name__)
            raise LLMUnavailableError("Embedding provider is unavailable", diagnostic_code="embedding_connection_error") from exc

        if response.status_code >= 500:
            raise LLMUnavailableError("Embedding provider is unavailable", diagnostic_code="embedding_provider_error")
        if response.status_code >= 400:
            raise LLMUpstreamError("Embedding provider rejected the request", diagnostic_code=f"embedding_http_{response.status_code}")

        try:
            body = response.json()
            rows = body["data"]
            if not isinstance(rows, list) or len(rows) != len(texts):
                raise ValueError("unexpected embedding count")
            ordered: list[list[float] | None] = [None] * len(texts)
            for row in rows:
                index = row["index"]
                vector = row["embedding"]
                if type(index) is not int or not 0 <= index < len(ordered) or ordered[index] is not None:
                    raise ValueError("invalid embedding index")
                if not isinstance(vector, list) or len(vector) != self.dimensions:
                    raise ValueError("invalid embedding dimensions")
                if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
                    raise ValueError("invalid embedding value")
                parsed = [float(value) for value in vector]
                if not all(math.isfinite(value) for value in parsed):
                    raise ValueError("non-finite embedding value")
                ordered[index] = parsed
            if any(vector is None for vector in ordered):
                raise ValueError("missing embedding")
            return [vector for vector in ordered if vector is not None]
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise LLMUpstreamError("Embedding provider returned an invalid response", diagnostic_code="invalid_embedding_response") from exc


def get_embedding_provider(settings: Settings) -> NebiusEmbeddingProvider | None:
    """Return the configured provider, or None to keep the index lexical-only.

    Reuse the existing LLM key only when its configured endpoint is Nebius; this avoids silently
    sending screened transaction text to an unrelated OpenAI-compatible provider.
    """
    api_key = settings.rag_embedding_api_key.strip()
    if not api_key:
        llm_host = urlparse(settings.llm_base_url).hostname
        if llm_host == NEBIUS_HOST:
            api_key = settings.llm_api_key.strip()
    if not api_key:
        return None
    return NebiusEmbeddingProvider(
        api_key=api_key,
        base_url=settings.rag_embedding_base_url,
        model=settings.rag_embedding_model,
        timeout=settings.rag_embedding_timeout_seconds,
        dimensions=EMBEDDING_DIMENSIONS,
    )
