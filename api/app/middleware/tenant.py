"""Tenant isolation middleware (Sprint 1).

This middleware decodes the bearer token (if present) and stuffs the
resulting ``org_id`` / ``user_id`` into ``request.state`` so downstream
handlers and the database session can pick them up.

It does NOT enforce auth — protected routes still call
``Depends(get_current_user)`` which raises 401 if the token is missing
or invalid. The middleware is best-effort: it tries to decode, and on
failure it just leaves the request state empty. The
``app.api.auth`` routes are explicitly excluded (they have to read the
body to validate credentials) and the webhook ingestion routes are
excluded too — those use the existing HMAC/Svix signature scheme and
are still publicly addressable by source id.

Public path prefixes (no token required):

* ``/api/auth/*``            — register / login / refresh
* ``/api/webhook/*``         — signed webhook ingestion
* ``/api/webhooks/github``   — GitHub webhooks (HMAC verified upstream)
* ``/health``, ``/``, ``/docs``, ``/redoc``, ``/openapi.json``
"""

from __future__ import annotations

import logging
import uuid
from typing import Iterable

from fastapi import Request
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.auth import decode_token, ACCESS

logger = logging.getLogger(__name__)


# Paths that should never require a token. Exact prefix match; a path
# must START with one of these to be skipped. Order matters — most
# specific first.
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/api/auth",
    "/api/webhook/",
    "/api/webhooks/github",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
)


def _is_public(path: str) -> bool:
    for prefix in PUBLIC_PREFIXES:
        if path == prefix or path.startswith(prefix):
            return True
    return False


class TenantIsolationMiddleware(BaseHTTPMiddleware):
    """Decode JWT, attach ``org_id``/``user_id`` to ``request.state``.

    The middleware is intentionally tolerant: a malformed or missing
    token does not raise — it just logs at debug level and lets the
    route-level dependencies decide. Routes that need authentication
    use ``Depends(get_current_user)`` which performs the real check.
    """

    def __init__(self, app: ASGIApp, public_prefixes: Iterable[str] | None = None):
        super().__init__(app)
        self.public_prefixes: tuple[str, ...] = tuple(public_prefixes or PUBLIC_PREFIXES)

    async def dispatch(self, request: Request, call_next):
        # Always reset state — important when the same request state
        # object is reused (it isn't, but defensive).
        request.state.org_id = None
        request.state.user_id = None
        request.state.token_type = None

        path = request.url.path
        is_public = any(
            path == p or path.startswith(p) for p in self.public_prefixes
        )

        if not is_public:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if auth and auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1].strip()
                try:
                    data = decode_token(token, expected_type=ACCESS)
                    request.state.org_id = data.org_id
                    request.state.user_id = data.user_id
                    request.state.token_type = data.type
                except Exception as exc:  # noqa: BLE001
                    # Bad tokens are fine here — a protected route will
                    # raise 401 via get_current_user. We only log once
                    # per request and at debug to avoid noise.
                    logger.debug("Tenant middleware: token rejected (%s)", exc)

        return await call_next(request)


def get_request_org_id(request: Request) -> uuid.UUID | None:
    """Convenience helper for handlers that need the JWT-stamped org_id."""
    return getattr(request.state, "org_id", None)
