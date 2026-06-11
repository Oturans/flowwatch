"""Tests for Sprint 3 v1 endpoints: thresholds, slack config, alerts.

Covers the new ``/api/v1/`` surface:

* ``GET / PATCH /api/v1/sources/{id}/thresholds``
* ``GET / POST /api/v1/sources/{id}/slack-config``
* ``GET /api/v1/alerts`` with filters
* ``PATCH /api/v1/alerts/{id}/acknowledge``
* ``PATCH /api/v1/alerts/{id}/dismiss``
* ``POST /api/v1/alerts/{id}/test-slack`` (mock httpx)

All endpoints require a logged-in user; we use the existing
``auth_headers_factory`` fixture to mint a token.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.auth import create_access_token
from app.database import AsyncSessionLocal
from app.models import (
    AnomalyEvent,
    AnomalyRule,
    RULE_LATENCY_P95,
    Tenant,
    User,
    WebhookSource,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user_and_headers():
    """Mint a fresh user with a tenant and return (user, headers)."""
    from app.core.auth import hash_password

    async with AsyncSessionLocal() as session:
        tenant = Tenant(
            name=f"T-{uuid.uuid4().hex[:6]}",
            slug=f"t-{uuid.uuid4().hex[:6]}",
            plan="free",
            is_active=True,
        )
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)

        user = User(
            email=f"u-{uuid.uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("supersecret123"),
            org_id=tenant.id,
            role="admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    token = create_access_token(user.id, user.org_id)
    return user, {"Authorization": f"Bearer {token}"}


async def _make_source(name: str = "n8n-prod", slack_url: str | None = None):
    sid = f"src-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        source = WebhookSource(
            id=sid,
            name=name,
            signing_secret="test-secret-1234",
            platform="n8n",
            alert_config=(
                {"slack_webhook_url": slack_url} if slack_url else {}
            ),
            is_active=True,
        )
        session.add(source)
        await session.commit()
    return sid


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


class TestThresholdsAPI:
    @pytest.mark.asyncio
    async def test_get_thresholds_empty(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        r = await client.get(
            f"/api/v1/sources/{source_id}/thresholds", headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source_id"] == source_id
        assert body["thresholds"] == []

    @pytest.mark.asyncio
    async def test_patch_thresholds_replaces_set(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        body = {
            "thresholds": [
                {"metric": "latency_ms", "value": 750.0, "window_seconds": 300},
                {"metric": "error_rate_pct", "value": 5.0, "window_seconds": 600},
                {"metric": "failure_count", "value": 3, "window_seconds": 900},
            ]
        }
        r = await client.patch(
            f"/api/v1/sources/{source_id}/thresholds",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(body),
        )
        assert r.status_code == 200, r.text
        resp = r.json()
        assert len(resp["thresholds"]) == 3
        metrics = {t["metric"] for t in resp["thresholds"]}
        assert metrics == {"latency_ms", "error_rate_pct", "failure_count"}

        # GET should return the same set.
        r2 = await client.get(
            f"/api/v1/sources/{source_id}/thresholds", headers=headers
        )
        assert r2.status_code == 200
        assert len(r2.json()["thresholds"]) == 3

    @pytest.mark.asyncio
    async def test_patch_thresholds_replaces_existing(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        # First write three.
        await client.patch(
            f"/api/v1/sources/{source_id}/thresholds",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(
                {
                    "thresholds": [
                        {"metric": "latency_ms", "value": 100.0},
                        {"metric": "error_rate_pct", "value": 1.0},
                        {"metric": "failure_count", "value": 5.0},
                    ]
                }
            ),
        )
        # Now replace with one.
        r = await client.patch(
            f"/api/v1/sources/{source_id}/thresholds",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(
                {
                    "thresholds": [
                        {"metric": "latency_ms", "value": 250.0},
                    ]
                }
            ),
        )
        assert r.status_code == 200
        assert len(r.json()["thresholds"]) == 1
        assert r.json()["thresholds"][0]["metric"] == "latency_ms"

    @pytest.mark.asyncio
    async def test_patch_rejects_duplicate_metrics(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        r = await client.patch(
            f"/api/v1/sources/{source_id}/thresholds",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(
                {
                    "thresholds": [
                        {"metric": "latency_ms", "value": 100.0},
                        {"metric": "latency_ms", "value": 200.0},
                    ]
                }
            ),
        )
        assert r.status_code == 422  # pydantic validation error

    @pytest.mark.asyncio
    async def test_patch_rejects_invalid_metric(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        r = await client.patch(
            f"/api/v1/sources/{source_id}/thresholds",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(
                {
                    "thresholds": [
                        {"metric": "made_up", "value": 100.0},
                    ]
                }
            ),
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_patch_rejects_negative_value(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        r = await client.patch(
            f"/api/v1/sources/{source_id}/thresholds",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(
                {
                    "thresholds": [
                        {"metric": "latency_ms", "value": -1.0},
                    ]
                }
            ),
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_patch_rejects_out_of_range_error_rate(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        r = await client.patch(
            f"/api/v1/sources/{source_id}/thresholds",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(
                {
                    "thresholds": [
                        {"metric": "error_rate_pct", "value": 200.0},
                    ]
                }
            ),
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_404_for_unknown_source(self, client):
        _user, headers = await _make_user_and_headers()
        r = await client.get(
            "/api/v1/sources/nope-9999/thresholds", headers=headers
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self, client):
        source_id = await _make_source()
        r = await client.get(f"/api/v1/sources/{source_id}/thresholds")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Slack config
# ---------------------------------------------------------------------------


class TestSlackConfigAPI:
    @pytest.mark.asyncio
    async def test_get_slack_config_empty(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        r = await client.get(
            f"/api/v1/sources/{source_id}/slack-config", headers=headers
        )
        assert r.status_code == 200
        body = r.json()
        assert body["webhook_url_set"] is False
        assert body["enabled"] is True

    @pytest.mark.asyncio
    async def test_set_slack_config(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        url = "https://hooks.slack.com/services/T0/B0/secret"
        r = await client.post(
            f"/api/v1/sources/{source_id}/slack-config",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(
                {
                    "webhook_url": url,
                    "enabled": True,
                    "channel_hint": "#ops",
                }
            ),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["webhook_url_set"] is True
        assert body["enabled"] is True
        assert body["channel_hint"] == "#ops"

    @pytest.mark.asyncio
    async def test_clear_slack_config(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source(slack_url="https://hooks.slack.com/x")
        r = await client.post(
            f"/api/v1/sources/{source_id}/slack-config",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps({"webhook_url": ""}),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["webhook_url_set"] is False

    @pytest.mark.asyncio
    async def test_rejects_non_slack_url(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        r = await client.post(
            f"/api/v1/sources/{source_id}/slack-config",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps({"webhook_url": "https://example.com/webhook"}),
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_disable_keeps_url(self, client):
        _user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        url = "https://hooks.slack.com/services/T0/B0/secret"
        # Set with enabled=True
        await client.post(
            f"/api/v1/sources/{source_id}/slack-config",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps({"webhook_url": url, "enabled": True}),
        )
        # Disable
        r = await client.post(
            f"/api/v1/sources/{source_id}/slack-config",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps({"enabled": False}),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["webhook_url_set"] is True
        assert body["enabled"] is False


# ---------------------------------------------------------------------------
# Alert list / acknowledge / dismiss
# ---------------------------------------------------------------------------


async def _make_event(
    *,
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    source_id: str | None = None,
    severity: str = "high",
    message: str = "p95 latency 1234ms exceeds threshold 500ms",
    detected_at: datetime | None = None,
    context: dict | None = None,
) -> AnomalyEvent:
    async with AsyncSessionLocal() as session:
        event = AnomalyEvent(
            org_id=org_id,
            rule_id=rule_id,
            source_id=source_id,
            severity=severity,
            message=message,
            context=context or {
                "rule_type": "latency_p95",
                "metric_value": 1234.0,
                "threshold": 500.0,
            },
        )
        if detected_at is not None:
            event.detected_at = detected_at
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event


async def _make_rule(org_id: uuid.UUID) -> AnomalyRule:
    async with AsyncSessionLocal() as session:
        rule = AnomalyRule(
            org_id=org_id,
            name="p95-too-high",
            rule_type=RULE_LATENCY_P95,
            threshold=500.0,
            window_seconds=300,
            enabled=True,
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule


class TestAlertListAPI:
    @pytest.mark.asyncio
    async def test_list_alerts_empty(self, client):
        _user, headers = await _make_user_and_headers()
        r = await client.get("/api/v1/alerts", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["page_size"] == 50
        assert body["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_alerts_with_data(self, client):
        user, headers = await _make_user_and_headers()
        source_id = await _make_source(name="n8n-prod")
        rule = await _make_rule(user.org_id)
        now = datetime.now(timezone.utc)
        for i in range(3):
            await _make_event(
                org_id=user.org_id,
                rule_id=rule.id,
                source_id=source_id,
                detected_at=now - timedelta(minutes=i),
            )
        r = await client.get("/api/v1/alerts", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3
        for item in body["items"]:
            assert item["source_id"] == source_id
            assert item["status"] == "open"
            assert item["severity"] == "high"

    @pytest.mark.asyncio
    async def test_filter_by_source_id(self, client):
        user, headers = await _make_user_and_headers()
        source_a = await _make_source(name="a")
        source_b = await _make_source(name="b")
        rule = await _make_rule(user.org_id)
        await _make_event(
            org_id=user.org_id, rule_id=rule.id, source_id=source_a
        )
        await _make_event(
            org_id=user.org_id, rule_id=rule.id, source_id=source_b
        )
        r = await client.get(
            f"/api/v1/alerts?source_id={source_a}", headers=headers
        )
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["source_id"] == source_a

    @pytest.mark.asyncio
    async def test_filter_by_severity(self, client):
        user, headers = await _make_user_and_headers()
        rule = await _make_rule(user.org_id)
        await _make_event(
            org_id=user.org_id, rule_id=rule.id, severity="high"
        )
        await _make_event(
            org_id=user.org_id, rule_id=rule.id, severity="low"
        )
        r = await client.get(
            "/api/v1/alerts?severity=high", headers=headers
        )
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["severity"] == "high"

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client):
        user, headers = await _make_user_and_headers()
        rule = await _make_rule(user.org_id)
        e1 = await _make_event(org_id=user.org_id, rule_id=rule.id)
        e2 = await _make_event(org_id=user.org_id, rule_id=rule.id)
        # Acknowledge e1
        async with AsyncSessionLocal() as session:
            row = await session.get(AnomalyEvent, e1.id)
            row.acknowledged = True
            row.acknowledged_at = datetime.now(timezone.utc)
            row.acknowledged_by = "user@example.com"
            await session.commit()
        # Dismiss e2
        async with AsyncSessionLocal() as session:
            row = await session.get(AnomalyEvent, e2.id)
            row.dismissed = True
            row.dismissed_at = datetime.now(timezone.utc)
            await session.commit()

        for status_value, expected_total in (
            ("open", 0),
            ("acknowledged", 1),
            ("dismissed", 1),
        ):
            r = await client.get(
                f"/api/v1/alerts?status={status_value}", headers=headers
            )
            assert r.status_code == 200
            assert r.json()["total"] == expected_total

    @pytest.mark.asyncio
    async def test_invalid_status_filter_rejected(self, client):
        _user, headers = await _make_user_and_headers()
        r = await client.get(
            "/api/v1/alerts?status=bogus", headers=headers
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_pagination(self, client):
        user, headers = await _make_user_and_headers()
        rule = await _make_rule(user.org_id)
        for _ in range(7):
            await _make_event(org_id=user.org_id, rule_id=rule.id)
        r = await client.get(
            "/api/v1/alerts?page=1&page_size=3", headers=headers
        )
        body = r.json()
        assert body["total"] == 7
        assert len(body["items"]) == 3
        assert body["has_more"] is True
        assert body["page"] == 1
        assert body["page_size"] == 3

    @pytest.mark.asyncio
    async def test_time_range_filter(self, client):
        user, headers = await _make_user_and_headers()
        rule = await _make_rule(user.org_id)
        now = datetime.now(timezone.utc)
        old = await _make_event(
            org_id=user.org_id,
            rule_id=rule.id,
            detected_at=now - timedelta(hours=2),
        )
        recent = await _make_event(
            org_id=user.org_id,
            rule_id=rule.id,
            detected_at=now - timedelta(minutes=5),
        )
        # Format the timestamp as a Z-suffixed string so the URL
        # query parameter doesn't need URL-encoding of the ``+``.
        start = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = await client.get(
            f"/api/v1/alerts?start={start}", headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        ids = {item["id"] for item in body["items"]}
        assert str(recent.id) in ids
        assert str(old.id) not in ids


class TestAlertAcknowledgeAPI:
    @pytest.mark.asyncio
    async def test_acknowledge_changes_status(self, client):
        user, headers = await _make_user_and_headers()
        source_id = await _make_source()
        rule = await _make_rule(user.org_id)
        event = await _make_event(
            org_id=user.org_id, rule_id=rule.id, source_id=source_id
        )
        r = await client.patch(
            f"/api/v1/alerts/{event.id}/acknowledge",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps({"acknowledged_by": "alice@example.com"}),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "acknowledged"
        assert body["acknowledged_by"] == "alice@example.com"
        assert body["acknowledged_at"] is not None

    @pytest.mark.asyncio
    async def test_acknowledge_idempotent(self, client):
        user, headers = await _make_user_and_headers()
        rule = await _make_rule(user.org_id)
        event = await _make_event(org_id=user.org_id, rule_id=rule.id)
        for body_text in (
            json.dumps({"acknowledged_by": "alice"}),
            json.dumps({"acknowledged_by": "bob"}),
        ):
            r = await client.patch(
                f"/api/v1/alerts/{event.id}/acknowledge",
                headers={**headers, "Content-Type": "application/json"},
                content=body_text,
            )
            assert r.status_code == 200
        # First call wins for "acknowledged_by" — we don't overwrite.
        r = await client.get(
            "/api/v1/alerts?status=acknowledged", headers=headers
        )
        item = next(i for i in r.json()["items"] if i["id"] == str(event.id))
        assert item["acknowledged_by"] == "alice"

    @pytest.mark.asyncio
    async def test_acknowledge_404(self, client):
        _user, headers = await _make_user_and_headers()
        r = await client.patch(
            f"/api/v1/alerts/{uuid.uuid4()}/acknowledge", headers=headers
        )
        assert r.status_code == 404


class TestAlertDismissAPI:
    @pytest.mark.asyncio
    async def test_dismiss_changes_status(self, client):
        user, headers = await _make_user_and_headers()
        rule = await _make_rule(user.org_id)
        event = await _make_event(org_id=user.org_id, rule_id=rule.id)
        r = await client.patch(
            f"/api/v1/alerts/{event.id}/dismiss",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps({"dismissed_by": "carol@example.com"}),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "dismissed"
        assert body["dismissed_by"] == "carol@example.com"
        assert body["dismissed_at"] is not None

    @pytest.mark.asyncio
    async def test_dismiss_takes_precedence_over_ack(self, client):
        user, headers = await _make_user_and_headers()
        rule = await _make_rule(user.org_id)
        event = await _make_event(org_id=user.org_id, rule_id=rule.id)
        # Ack first
        await client.patch(
            f"/api/v1/alerts/{event.id}/acknowledge",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps({}),
        )
        # Then dismiss
        r = await client.patch(
            f"/api/v1/alerts/{event.id}/dismiss",
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps({}),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "dismissed"
        # Both timestamps are populated.
        assert body["acknowledged_at"] is not None
        assert body["dismissed_at"] is not None

    @pytest.mark.asyncio
    async def test_dismiss_idempotent(self, client):
        user, headers = await _make_user_and_headers()
        rule = await _make_rule(user.org_id)
        event = await _make_event(org_id=user.org_id, rule_id=rule.id)
        for body_text in (
            json.dumps({"dismissed_by": "alice"}),
            json.dumps({"dismissed_by": "bob"}),
        ):
            r = await client.patch(
                f"/api/v1/alerts/{event.id}/dismiss",
                headers={**headers, "Content-Type": "application/json"},
                content=body_text,
            )
            assert r.status_code == 200
        # First call wins.
        r = await client.get(
            "/api/v1/alerts?status=dismissed", headers=headers
        )
        item = next(i for i in r.json()["items"] if i["id"] == str(event.id))
        assert item["dismissed_by"] == "alice"

    @pytest.mark.asyncio
    async def test_dismiss_404(self, client):
        _user, headers = await _make_user_and_headers()
        r = await client.patch(
            f"/api/v1/alerts/{uuid.uuid4()}/dismiss", headers=headers
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Test-slack endpoint (mock httpx)
# ---------------------------------------------------------------------------


class TestTestSlackEndpoint:
    @pytest.mark.asyncio
    async def test_test_slack_with_configured_source(self, client):
        user, headers = await _make_user_and_headers()
        url = "https://hooks.slack.com/services/T0/B0/secret"
        source_id = await _make_source(slack_url=url)
        rule = await _make_rule(user.org_id)
        event = await _make_event(
            org_id=user.org_id, rule_id=rule.id, source_id=source_id
        )

        # Patch the notifier used inside the route via a dependency
        # override would be cleaner, but the route constructs its
        # own notifier. We patch the module-level reference.
        from app.routes import sprint3 as sprint3_mod

        original = sprint3_mod.SlackNotifier
        try:
            sprint3_mod.SlackNotifier = MagicMock(
                return_value=MagicMock(send=AsyncMock(return_value=True))
            )
            r = await client.post(
                f"/api/v1/alerts/{event.id}/test-slack", headers=headers
            )
        finally:
            sprint3_mod.SlackNotifier = original
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sent"] is True
        assert body["source_id"] == source_id

    @pytest.mark.asyncio
    async def test_test_slack_409_when_no_url(self, client):
        user, headers = await _make_user_and_headers()
        source_id = await _make_source()  # no slack URL
        rule = await _make_rule(user.org_id)
        event = await _make_event(
            org_id=user.org_id, rule_id=rule.id, source_id=source_id
        )
        r = await client.post(
            f"/api/v1/alerts/{event.id}/test-slack", headers=headers
        )
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_test_slack_404_for_unknown_alert(self, client):
        _user, headers = await _make_user_and_headers()
        r = await client.post(
            f"/api/v1/alerts/{uuid.uuid4()}/test-slack", headers=headers
        )
        assert r.status_code == 404
