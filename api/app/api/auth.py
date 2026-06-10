"""Auth API: register, login, refresh, me (Sprint 1).

Routes:

* ``POST /api/auth/register``  — create a tenant + first admin user.
* ``POST /api/auth/login``     — exchange email + password for a JWT pair.
* ``POST /api/auth/refresh``   — rotate a refresh token into a fresh pair.
* ``GET  /api/auth/me``        — return the current user + tenant.

The register endpoint is the *only* place that creates a tenant.
Subsequent users must be invited via the tenant management API (TBD in
a later sprint).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import (
    REFRESH,
    User,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import Tenant
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TenantResponse,
    TokenPair,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_token_pair(user: User) -> TokenPair:
    """Issue a fresh access + refresh token for ``user``."""
    settings = get_settings()
    return TokenPair(
        access_token=create_access_token(user.id, user.org_id),
        refresh_token=create_refresh_token(user.id, user.org_id),
        token_type="bearer",
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )


def _user_to_response(user: User) -> UserResponse:
    return UserResponse.model_validate(user)


def _tenant_to_response(tenant: Tenant) -> TenantResponse:
    return TenantResponse.model_validate(tenant)


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new tenant and its first admin user."""
    # 1) Check slug uniqueness up front for a nice error message.
    existing = await db.execute(
        select(Tenant).where(Tenant.slug == body.tenant.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant slug already taken",
        )

    # 2) Check email uniqueness.
    existing_user = await db.execute(
        select(User).where(User.email == body.user.email)
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # 3) Create tenant.
    tenant = Tenant(
        name=body.tenant.name,
        slug=body.tenant.slug,
        plan=body.tenant.plan,
        is_active=True,
    )
    db.add(tenant)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant or user conflict (concurrent registration?)",
        )

    # 4) Create the first user as admin.
    user = User(
        email=str(body.user.email).lower(),
        hashed_password=hash_password(body.user.password),
        full_name=body.user.full_name,
        org_id=tenant.id,
        role="admin",  # the first user of a tenant is always admin
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(user)

    return RegisterResponse(
        user=_user_to_response(user),
        tenant=_tenant_to_response(tenant),
        tokens=_build_token_pair(user),
    )


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Exchange email + password for an access + refresh token."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(User)
        .where(User.email == str(body.email).lower())
        .options(selectinload(User.tenant))
    )
    user = result.scalar_one_or_none()

    # Verify password even when user is missing to keep timing similar
    # (passlib is fast; we still want a comparable response shape).
    fake_hash = "$2b$04$" + "x" * 53
    password_ok = verify_password(
        body.password,
        user.hashed_password if user else fake_hash,
    )
    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is deactivated",
        )

    if not user.tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is deactivated",
        )

    return _build_token_pair(user)


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Rotate a refresh token into a fresh access + refresh pair."""
    data = decode_token(body.refresh_token, expected_type=REFRESH)

    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(User)
        .where(User.id == data.user_id)
        .options(selectinload(User.tenant))
    )
    user = result.scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or user.org_id != data.org_id
        or user.tenant is None
        or not user.tenant.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or token mismatch",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Rotate: every refresh issues a *new* pair. The old refresh token
    # remains technically valid until its own ``exp``; production
    # systems would track a revocation list. Sprint 1 keeps it simple.
    return _build_token_pair(user)


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------


@router.get("/me", response_model=MeResponse)
async def me(current: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return the authenticated user + their tenant."""
    # ``current.tenant`` is loaded via the relationship; no extra query
    # needed.
    if current.tenant is None:
        # Defensive — should never happen because of the FK + cascade.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authenticated user has no tenant",
        )
    return MeResponse(
        user=_user_to_response(current),
        tenant=_tenant_to_response(current.tenant),
    )
