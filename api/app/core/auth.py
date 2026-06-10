"""JWT auth + password hashing primitives (Sprint 1).

Tokens encode ``sub`` (user id) and ``org_id`` (tenant id) plus a
``type`` discriminator so we can refuse to accept a refresh token as
an access token (or vice versa).

The module exposes FastAPI dependencies for:

* ``get_current_user`` — read ``Authorization: Bearer <jwt>`` from the
  request, verify it, and return the matching ``User`` row.
* ``require_org_access`` — like ``get_current_user`` but additionally
  verifies the user belongs to the ``org_id`` carried in the URL.

Passwords are hashed with passlib's bcrypt scheme. We avoid the
cryptography backend and stick to the pure-Python bcrypt for speed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models import Tenant, User


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

# bcrypt with a low rounds-count so test runs stay fast. Production
# deployments should bump ``rounds`` via environment.
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=4,
)


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff ``plain`` matches the bcrypt-hashed ``hashed``."""
    try:
        return _pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        # Malformed hashes must never authenticate.
        return False


# ---------------------------------------------------------------------------
# JWT encode / decode
# ---------------------------------------------------------------------------

# Token kinds. Both are JWTs but the ``type`` claim keeps them apart.
ACCESS = "access"
REFRESH = "refresh"

# FastAPI's OAuth2 helper. We use ``auto_error=False`` so we can return
# our own error payload (the default 403 doesn't include a ``detail``).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


@dataclass(frozen=True)
class TokenData:
    """Decoded JWT payload (validated)."""

    user_id: uuid.UUID
    org_id: uuid.UUID
    type: str
    exp: datetime


def _settings():
    return get_settings()


def _make_token(
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    token_type: str,
    expires_delta: timedelta,
) -> str:
    """Build a signed JWT for the given user/org/type."""
    settings = _settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    """Issue a short-lived access token."""
    settings = _settings()
    return _make_token(
        user_id,
        org_id,
        ACCESS,
        timedelta(minutes=settings.jwt_access_ttl_minutes),
    )


def create_refresh_token(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    """Issue a longer-lived refresh token."""
    settings = _settings()
    return _make_token(
        user_id,
        org_id,
        REFRESH,
        timedelta(minutes=settings.jwt_refresh_ttl_minutes),
    )


def decode_token(token: str, expected_type: Optional[str] = None) -> TokenData:
    """Verify signature + exp, optionally enforce token ``type``.

    Raises ``HTTPException(401)`` on any failure. We deliberately don't
    leak which check failed (signature vs expiry vs type) to keep the
    attack surface small.
    """
    settings = _settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    org_id_raw = payload.get("org_id")
    token_type = payload.get("type")
    exp_ts = payload.get("exp")
    if not (sub and org_id_raw and token_type and exp_ts is not None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if expected_type is not None and token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Expected {expected_type} token, got {token_type}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return TokenData(
            user_id=uuid.UUID(sub),
            org_id=uuid.UUID(org_id_raw),
            type=token_type,
            exp=datetime.fromtimestamp(exp_ts, tz=timezone.utc),
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token ids",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the bearer token to a ``User`` row (active access token)."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    data = decode_token(token, expected_type=ACCESS)
    # Eagerly load the tenant relationship so handlers can read
    # ``user.tenant`` without triggering a lazy load (which would
    # fail outside the request session).
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(User).where(User.id == data.user_id).options(selectinload(User.tenant))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is deactivated",
        )
    return user


def require_org_access(org_id: uuid.UUID):
    """Build a dependency that enforces the user belongs to ``org_id``.

    Usage::

        @router.get("/orgs/{org_id}/things")
        async def list_things(
            user: User = Depends(require_org_access(org_id)),
        ):
            ...

    Admins (role='admin') may always access; members/viewers are bound
    to their own org. A mismatch returns 403.
    """

    async def _checker(
        user: User = Depends(get_current_user),
    ) -> User:
        if user.org_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: user does not belong to this organization",
            )
        return user

    return _checker
