"""Sprint 1 — auth schema unit tests.

Pydantic-only checks; no DB. Verifies the input validation rules on
``TenantCreate``, ``UserCreate``, ``LoginRequest``, ``RegisterRequest``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TenantCreate,
    UserCreate,
)


class TestTenantCreate:
    def test_minimal(self):
        t = TenantCreate(name="Acme", slug="acme")
        assert t.plan == "free"
        assert t.slug == "acme"

    def test_slug_is_lowercased(self):
        # The pattern is enforced on the input; the lower-casing is
        # a defensive normalization for mixed-case values that somehow
        # slip through (e.g. callers that bypass pattern validation).
        # Call the validator directly to prove the normalization logic.
        assert TenantCreate._slug_lower("ACME") == "acme"

    @pytest.mark.parametrize("bad", ["Bad Slug", "-leading", "trailing-", "with space", ""])
    def test_bad_slugs(self, bad):
        with pytest.raises(ValidationError):
            TenantCreate(name="Acme", slug=bad)

    @pytest.mark.parametrize("ok", ["acme", "acme-1", "abc-123-def", "1-2-3"])
    def test_good_slugs(self, ok):
        t = TenantCreate(name="Acme", slug=ok)
        assert t.slug == ok

    def test_empty_name(self):
        with pytest.raises(ValidationError):
            TenantCreate(name="", slug="acme")


class TestUserCreate:
    def test_minimal(self):
        u = UserCreate(email="a@b.com", password="hunter2hunter")
        assert u.full_name is None

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            UserCreate(email="a@b.com", password="short")

    @pytest.mark.parametrize(
        "bad",
        ["not-an-email", "a@", "@b.com", "no-at-sign", "spaces in@email.com"],
    )
    def test_bad_emails(self, bad):
        with pytest.raises(ValidationError):
            UserCreate(email=bad, password="hunter2hunter")

    def test_email_lowercased(self):
        u = UserCreate(email="MIXED@CASE.com", password="hunter2hunter")
        assert u.email == "mixed@case.com"


class TestLoginRequest:
    def test_ok(self):
        r = LoginRequest(email="a@b.com", password="hunter2hunter")
        assert r.email == "a@b.com"

    def test_empty_password_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="a@b.com", password="")

    def test_bad_email_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="nope", password="hunter2hunter")


class TestRegisterRequest:
    def test_nested(self):
        body = RegisterRequest(
            tenant=TenantCreate(name="Acme", slug="acme"),
            user=UserCreate(email="a@b.com", password="hunter2hunter"),
        )
        assert body.tenant.slug == "acme"
        assert body.user.email == "a@b.com"
