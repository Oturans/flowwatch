"""Pydantic schemas for auth (Sprint 1)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.tenant import ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER, VALID_ROLES

# Simple RFC-5322-ish email check. We avoid pydantic's EmailStr because
# it rejects reserved / special-use TLDs (``.test``, ``.example``,
# ``.localhost``) that we use heavily in the test suite, and that
# block a *lot* of perfectly valid real-world use cases for an MVP.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(v: str) -> str:
    if not isinstance(v, str) or not _EMAIL_RE.match(v):
        raise ValueError("value is not a valid email address")
    return v.lower()


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    plan: str = Field("free", max_length=32)

    @field_validator("slug")
    @classmethod
    def _slug_lower(cls, v: str) -> str:
        return v.lower()


class UserCreate(BaseModel):
    email: str
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _validate_email(v)


class RegisterRequest(BaseModel):
    """Body for ``POST /api/auth/register``.

    Creates a new tenant AND its first admin user in one call.
    """

    tenant: TenantCreate
    user: UserCreate


class LoginRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _validate_email(v)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str]
    org_id: uuid.UUID
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class RegisterResponse(BaseModel):
    user: UserResponse
    tenant: TenantResponse
    tokens: TokenPair


class MeResponse(BaseModel):
    user: UserResponse
    tenant: TenantResponse


__all__ = [
    "TenantCreate",
    "UserCreate",
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "TokenPair",
    "UserResponse",
    "TenantResponse",
    "RegisterResponse",
    "MeResponse",
    "VALID_ROLES",
    "ROLE_ADMIN",
    "ROLE_MEMBER",
    "ROLE_VIEWER",
]
