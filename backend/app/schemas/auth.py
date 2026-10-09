from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuthUser(BaseModel):
    id: UUID
    email: str


class Profile(BaseModel):
    id: UUID
    display_name: str
    created_at: datetime
    updated_at: datetime


class Account(BaseModel):
    user: AuthUser
    profile: Profile


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=100)
