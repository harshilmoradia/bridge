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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
