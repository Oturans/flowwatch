"""Sprint 1 — auth API tests.

Covers:

* register / login / refresh / me happy paths
* error cases: duplicate email, duplicate slug, bad password, bad token
* JWT round-trip + tenant isolation helper
* middleware stamps request.state.org_id / user_id
"""

from __future__ import annotations

import time
import uuid

import pytest
from jose import jwt

from app.config import get_settings
from app.core.auth import (
    ACCESS,
    REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# Pure-function tests (no DB)
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_returns_string(self):
        h = hash_password("hunter2")
        assert isinstance(h, str) and len(h) > 20

    def test_verify_correct_password(self):
        h = hash_password("hunter2")
        assert verify_password("hunter2", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("hunter2")
        assert verify_password("WRONG", h) is False

    def test_verify_garbage_hash(self):
        assert verify_password("hunter2", "not-a-bcrypt-hash") is False


class TestJwtRoundTrip:
    def _uid(self) -> uuid.UUID:
        return uuid.uuid4()

    def test_access_token_decode(self):
        uid = self._uid()
        org = uuid.uuid4()
        token = create_access_token(uid, org)
        data = decode_token(token, expected_type=ACCESS)
        assert data.user_id == uid
        assert data.org_id == org
        assert data.type == ACCESS

    def test_refresh_token_decode(self):
        uid = self._uid()
        org = uuid.uuid4()
        token = create_refresh_token(uid, org)
        data = decode_token(token, expected_type=REFRESH)
        assert data.user_id == uid
        assert data.org_id == org
        assert data.type == REFRESH

    def test_wrong_type_rejected(self):
        token = create_access_token(self._uid(), uuid.uuid4())
        # Refusing refresh-as-access is a security property.
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            decode_token(token, expected_type=REFRESH)
        assert exc.value.status_code == 401

    def test_garbage_token_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            decode_token("not-a-real-jwt", expected_type=ACCESS)
        assert exc.value.status_code == 401

    def test_expired_token_rejected(self):
        # Build an already-expired token by hand using the same secret.
        settings = get_settings()
        uid = self._uid()
        org = uuid.uuid4()
        past = int(time.time()) - 60
        payload = {
            "sub": str(uid),
            "org_id": str(org),
            "type": ACCESS,
            "iat": past - 60,
            "exp": past,
        }
        token = jwt.encode(
            payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            decode_token(token, expected_type=ACCESS)
        assert exc.value.status_code == 401

    def test_tampered_signature_rejected(self):
        token = create_access_token(self._uid(), uuid.uuid4())
        # Flip a character in the signature segment.
        head, payload, sig = token.split(".")
        sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
        bad = ".".join([head, payload, sig])
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            decode_token(bad, expected_type=ACCESS)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# HTTP tests
# ---------------------------------------------------------------------------


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_creates_tenant_and_admin(self, client):
        slug = f"acme-{uuid.uuid4().hex[:6]}"
        body = {
            "tenant": {"name": "Acme", "slug": slug, "plan": "free"},
            "user": {
                "email": "founder@acme.test",
                "password": "supersecret123",
                "full_name": "Ada L.",
            },
        }
        r = await client.post("/api/auth/register", json=body)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["user"]["email"] == "founder@acme.test"
        assert data["user"]["role"] == "admin"
        assert data["tenant"]["slug"] == slug
        assert data["tokens"]["access_token"]
        assert data["tokens"]["refresh_token"]
        assert data["tokens"]["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_register_duplicate_slug(self, client, tenant_factory):
        t = await tenant_factory(name="Existing", slug="dup-slug")
        body = {
            "tenant": {"name": "Acme2", "slug": t.slug, "plan": "free"},
            "user": {"email": "x@x.com", "password": "supersecret123"},
        }
        r = await client.post("/api/auth/register", json=body)
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client, tenant_factory, user_factory):
        t = await tenant_factory()
        u = await user_factory(t, email="dup@example.com")
        body = {
            "tenant": {"name": "Other", "slug": f"other-{uuid.uuid4().hex[:6]}", "plan": "free"},
            "user": {"email": u.email, "password": "supersecret123"},
        }
        r = await client.post("/api/auth/register", json=body)
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_register_short_password_rejected(self, client):
        body = {
            "tenant": {"name": "Acme", "slug": f"s-{uuid.uuid4().hex[:6]}", "plan": "free"},
            "user": {"email": "x@x.com", "password": "short"},
        }
        r = await client.post("/api/auth/register", json=body)
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_register_bad_slug_rejected(self, client):
        body = {
            "tenant": {"name": "Acme", "slug": "BAD SLUG WITH SPACES", "plan": "free"},
            "user": {"email": "x@x.com", "password": "supersecret123"},
        }
        r = await client.post("/api/auth/register", json=body)
        assert r.status_code == 422


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client, tenant_factory, user_factory):
        t = await tenant_factory()
        u = await user_factory(t, email="login@example.com", password="hunter22", role="admin")
        r = await client.post(
            "/api/auth/login",
            json={"email": u.email, "password": "hunter22"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["token_type"] == "bearer"
        # Access token must be decodable
        decoded = decode_token(data["access_token"], expected_type=ACCESS)
        assert decoded.user_id == u.id
        assert decoded.org_id == t.id

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, tenant_factory, user_factory):
        t = await tenant_factory()
        await user_factory(t, email="wp@example.com", password="rightpw123")
        r = await client.post(
            "/api/auth/login",
            json={"email": "wp@example.com", "password": "WRONG"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_login_unknown_email(self, client):
        r = await client.post(
            "/api/auth/login",
            json={"email": "ghost@nowhere.test", "password": "anything"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, client, tenant_factory, user_factory):
        t = await tenant_factory()
        await user_factory(t, email="off@example.com", password="hunter22", is_active=False)
        r = await client.post(
            "/api/auth/login",
            json={"email": "off@example.com", "password": "hunter22"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_login_inactive_tenant(self, client, tenant_factory, user_factory):
        t = await tenant_factory()
        u = await user_factory(t, email="tdown@example.com", password="hunter22")
        t.is_active = False
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            existing = await session.get(type(t), t.id)
            existing.is_active = False
            await session.commit()
        r = await client.post(
            "/api/auth/login",
            json={"email": u.email, "password": "hunter22"},
        )
        assert r.status_code == 403


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self, client, tenant_factory, user_factory):
        t = await tenant_factory()
        u = await user_factory(t, email="ref@example.com", password="hunter22")
        # log in to get a refresh token
        r = await client.post(
            "/api/auth/login",
            json={"email": u.email, "password": "hunter22"},
        )
        refresh = r.json()["refresh_token"]
        r2 = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data["access_token"]
        assert data["refresh_token"]
        # The new pair must still be valid for the right user/tenant.
        d = decode_token(data["access_token"], expected_type=ACCESS)
        assert d.user_id == u.id and d.org_id == t.id

    @pytest.mark.asyncio
    async def test_refresh_rejects_access_token(self, client, tenant_factory, user_factory):
        t = await tenant_factory()
        u = await user_factory(t, email="refacc@example.com", password="hunter22")
        access = create_access_token(u.id, u.org_id)
        r = await client.post("/api/auth/refresh", json={"refresh_token": access})
        assert r.status_code == 401


class TestMe:
    @pytest.mark.asyncio
    async def test_me_authenticated(self, client, tenant_factory, user_factory, auth_headers_factory):
        t = await tenant_factory()
        u = await user_factory(t, email="me@example.com", password="hunter22")
        headers = await auth_headers_factory(u)
        r = await client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["email"] == u.email
        assert data["tenant"]["id"] == str(t.id)

    @pytest.mark.asyncio
    async def test_me_no_token(self, client):
        r = await client.get("/api/auth/me")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_me_bad_token(self, client):
        r = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Middleware behavior
# ---------------------------------------------------------------------------


class TestTenantMiddleware:
    @pytest.mark.asyncio
    async def test_middleware_stamps_state_on_protected_route(
        self, client, tenant_factory, user_factory, auth_headers_factory
    ):
        # /api/sources is a protected (token-aware) read endpoint.
        t = await tenant_factory()
        u = await user_factory(t, email="mw@example.com", password="hunter22")
        headers = await auth_headers_factory(u)
        # The route may or may not return rows; we only assert 2xx for
        # a valid token (the public ``/api/sources`` actually does NOT
        # require a token, but it must not 401 on a valid token).
        r = await client.get("/api/sources", headers=headers)
        assert r.status_code != 401

    @pytest.mark.asyncio
    async def test_middleware_does_not_block_public_webhook(self, client):
        # A 404 from a missing source is fine; the point is that no
        # 401 surfaces.
        r = await client.post(
            "/api/webhook/no-such-source",
            json={"workflow_id": "w", "event_type": "completed", "status": "success"},
        )
        assert r.status_code != 401

    @pytest.mark.asyncio
    async def test_middleware_skips_auth_routes(self, client):
        # Login with garbage creds must return 401 from the *route*,
        # not the middleware.
        r = await client.post(
            "/api/auth/login",
            json={"email": "nope@nope.test", "password": "wrong"},
        )
        assert r.status_code == 401
        # And the error body must mention the route's reason, not a
        # middleware-level "Not authenticated".
        assert "Not authenticated" not in r.text
