from functools import lru_cache
import base64
import json
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "bridge-backend"
    environment: Literal["development", "staging", "production"] = "development"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    llm_provider: Literal["stub", "openai_compatible"] = "stub"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    rag_embedding_api_key: str = ""
    rag_embedding_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    rag_embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    rag_embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    rag_index_batch_size: int = Field(default=32, ge=1, le=64)
    rag_index_lease_seconds: int = Field(default=900, ge=60, le=3600)
    supabase_url: str = ""
    supabase_publishable_key: str = ""

    @field_validator("supabase_publishable_key")
    @classmethod
    def validate_supabase_key(cls, value: str) -> str:
        value = value.strip()
        if not value or (value.startswith("sb_publishable_") and len(value) > len("sb_publishable_")):
            return value
        # This only rejects privileged keys in configuration; Auth verifies JWTs.
        try:
            payload = value.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if isinstance(claims, dict) and claims.get("role") == "anon":
                return value
        except (IndexError, ValueError, UnicodeDecodeError):
            pass
        raise ValueError("Use a Supabase publishable key or legacy anon key, never a secret/service_role key")

    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or not parsed.hostname:
            raise ValueError("SUPABASE_URL must be a project origin")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
            raise ValueError("SUPABASE_URL must use HTTPS (HTTP is allowed only for local development)")
        return value

    @field_validator("rag_embedding_base_url")
    @classmethod
    def validate_rag_embedding_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if (parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/v1") or not parsed.hostname):
            raise ValueError("RAG_EMBEDDING_BASE_URL must be an API origin, optionally ending in /v1")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
        ):
            raise ValueError("RAG_EMBEDDING_BASE_URL must use HTTPS")
        return value

    @field_validator("rag_embedding_model")
    @classmethod
    def validate_rag_embedding_model(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("RAG_EMBEDDING_MODEL must be a non-empty model id without whitespace")
        if value != "Qwen/Qwen3-Embedding-8B":
            raise ValueError(
                "RAG_EMBEDDING_MODEL must match the verified Nebius model; "
                "changing models requires validation against the vector schema"
            )
        return value

    # Supabase transaction pooler (port 6543). Backend only.
    database_url: str = ""
    dataset: str = "northbrook-2026-10"
    # Demo routers (/api/v1 reads, later runs and decisions) accept callers without a bearer token.
    public_demo_api: bool = True

    # Model tiers used by the agents (see docs/architecture.md)
    model_nano: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    model_super: str = "nvidia/nemotron-3-super-120b-a12b"
    model_ultra: str = "nvidia/Nemotron-3-Ultra-550b-a55b"

    # Per-call timeout (seconds) by tier; reasoning models on Super/Ultra are slower.
    llm_timeout_nano: float = 30.0
    llm_timeout_super: float = 90.0
    llm_timeout_ultra: float = 180.0
    # Send response_format=json_object on JSON calls. Turn off if Token Factory rejects it.
    llm_json_response_format: bool = True

    # Built frontend (frontend/dist). Set in the Docker image; empty means API only.
    static_dir: str = ""
    # Public https URL, set by Render. Inngest syncs it as the app URL (the proxy hides https).
    render_external_url: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
