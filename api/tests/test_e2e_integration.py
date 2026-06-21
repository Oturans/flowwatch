"""
Sprint 5 — End-to-end integration tests for the FlowWatch API.

These tests exercise the full pipeline *through the HTTP boundary* of the
FastAPI app, using :class:`httpx.AsyncClient` with an in-process
``ASGITransport``. External services (Slack, GitHub) are mocked so the
suite is hermetic and runs in CI without network access.

Pipeline covered:
    1. Webhook ingestion        POST /api/webhook/{id}
    2. Health check              GET  /api/health
    3. Alert dispatcher          app.alerts.dispatch.dispatch_slack_for_findings
    4. Manual retry              POST /api/events/{id}/retry
    5. GitHub webhook            POST /webhooks/github + health
"""

from __future__ import annotations

import hmac
import hashlib
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.alerts.slack import SlackNotifier
from app.alerts.dispatch import dispatch_slack_for_findings
from app.database import AsyncSessionLocal
from app.models import AnomalyEvent, AnomalyRule, RULE_LATENCY_P95, WebhookSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def _event_payload(*, workflow_id: str, status: str = "success", run_id: str = "run-1") -> dict:
    return {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "event_type": "completed",
        "status": status,
        "payload": {"node": "node-A", "duration_ms": 1234},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    with patch("app.routes.webhooks.redis_client") as m:
        m.get = AsyncMock(return_value=None)
        m.setex = AsyncMock(return_value=True)
        m.incr = AsyncMock(return_value=1)
        m.lpush = AsyncMock(return_value=1)
        m.publish = AsyncMock(return_value=1)
        yield m


@pytest.fixture
def mock_redis_pubsub():
    """Mock the pubsub client (used for SSE fan-out) — also bound to a
    previous event loop after the conftest disposes the engine. The real
    client connection becomes stale, so we must replace it too.
    """
    with patch("app.routes.webhooks.redis_pubsub") as m:
        m.publish = AsyncMock(return_value=1)
        yield m


@pytest.fixture
def mock_redis_rate_limit():
    with patch("app.routes.webhooks.redis_rate_limit") as m:
        m.get = AsyncMock(return_value=None)
        m.setex = AsyncMock(return_value=True)
        m.incr = AsyncMock(return_value=1)
        yield m


@pytest.fixture
def mock_celery_dispatch():
    with patch("app.tasks.tasks.process_event") as task:
        task.delay = MagicMock(return_value=None)
        yield task


@pytest.fixture
def mock_slack_send():
    """Patch SlackNotifier.send at the class level so no real HTTP call happens."""
    with patch.object(SlackNotifier, "send", new=AsyncMock(return_value=True)) as send:
        yield send


@pytest_asyncio.fixture
async def github_e2e_source():
    """Seed a GitHub-platform source with a unique repo mapping."""
    from sqlalchemy import delete

    sid = f"gh-e2e-{uuid.uuid4().hex[:8]}"
    repo = f"org/{uuid.uuid4().hex[:6]}"
    secret = "github-e2e-secret-1234"

    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(WebhookSource).where(WebhookSource.platform == "github")
        )
        await session.commit()

    src = WebhookSource(
        id=sid,
        name="E2E GitHub",
        signing_secret=secret,
        platform="github",
        alert_config={"github_repo": repo, "max_retries": 3},
        is_active=True,
    )
    async with AsyncSessionLocal() as session:
        session.add(src)
        await session.commit()
    return {"id": sid, "repo": repo, "secret": secret}


@pytest_asyncio.fixture
async def tenant_with_slack_source():
    """Seed a tenant + WebhookSource with a Slack webhook URL, return (tenant, source)."""
    from app.models import Tenant

    async with AsyncSessionLocal() as session:
        t = Tenant(
            name=f"E2E-T-{uuid.uuid4().hex[:6]}",
            slug=f"t-{uuid.uuid4().hex[:6]}",
            plan="free",
            is_active=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)

        sid = f"slack-e2e-{uuid.uuid4().hex[:8]}"
        src = WebhookSource(
            id=sid,
            name="E2E Slack Source",
            signing_secret="slack-e2e-secret-1234",
            platform="n8n",
            alert_config={
                "slack_webhook_url": "https://hooks.slack.com/services/E2E/TEST/abc",
                "mute_windows": [],
            },
            is_active=True,
        )
        session.add(src)
        await session.commit()
        await session.refresh(src)
    return t, src


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebhookIngestThenHealth:
    """Webhook → DB row → health check stays green."""

    @pytest.mark.asyncio
    async def test_webhook_accepted_and_health_ok(
        self, client, mock_redis, mock_redis_rate_limit, mock_redis_pubsub, mock_celery_dispatch, seeded_source
    ):
        event = _event_payload(workflow_id="wf-e2e-1", status="success")
        body = json.dumps(event).encode()
        signature = _sign(body, seeded_source.signing_secret)

        ingest = await client.post(
            f"/api/webhook/{seeded_source.id}",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hmac-signature": signature,
                "x-message-id": f"msg-{uuid.uuid4().hex[:8]}",
            },
        )
        assert ingest.status_code == 200, ingest.text
        data = ingest.json()
        assert data["status"] == "accepted"
        assert "event_id" in data
        assert mock_celery_dispatch.delay.called

        # Health endpoint reachable.
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        # The list endpoint is reachable (events are persisted by the
        # stubbed Celery task in this test, so the new row will not be
        # in the listing — we only assert the route is wired).
        listed = await client.get(f"/api/events?source_id={seeded_source.id}")
        assert listed.status_code == 200
        assert isinstance(listed.json(), list)


class TestWebhookIngestInvalidSignature:
    @pytest.mark.asyncio
    async def test_bad_signature_returns_401(
        self, client, mock_redis, mock_redis_rate_limit, mock_redis_pubsub, mock_celery_dispatch, seeded_source
    ):
        event = _event_payload(workflow_id="wf-bad-sig")
        body = json.dumps(event).encode()
        bad_sig = "sha256=" + "0" * 64

        resp = await client.post(
            f"/api/webhook/{seeded_source.id}",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hmac-signature": bad_sig,
                "x-message-id": f"msg-{uuid.uuid4().hex[:8]}",
            },
        )
        assert resp.status_code == 401
        assert not mock_celery_dispatch.delay.called


class TestAlertDispatchEndToEnd:
    """E2E: AnomalyEvent row → dispatcher → SlackNotifier.send (mocked)."""

    @pytest.mark.asyncio
    async def test_slack_dispatch_calls_notifier_for_configured_source(
        self, mock_slack_send, tenant_with_slack_source
    ):
        tenant, src = tenant_with_slack_source
        async with AsyncSessionLocal() as session:
            rule = AnomalyRule(
                org_id=tenant.id,
                name="e2e-rule",
                rule_type=RULE_LATENCY_P95,
                threshold=500.0,
                window_seconds=300,
                enabled=True,
            )
            session.add(rule)
            await session.commit()
            await session.refresh(rule)

            event = AnomalyEvent(
                org_id=tenant.id,
                rule_id=rule.id,
                source_id=src.id,
                severity="high",
                message="e2e",
                context={
                    "rule_type": "latency_p95",
                    "metric_value": 1234.0,
                    "threshold": 500.0,
                },
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            event_id = event.id

            refreshed = await session.get(AnomalyEvent, event_id, populate_existing=True)
            results = await dispatch_slack_for_findings(
                session, [refreshed], notifier=SlackNotifier()
            )

        assert results == [True]
        assert mock_slack_send.await_count == 1
        # The first positional arg should be a Slack URL; second a SlackPayload.
        args, _ = mock_slack_send.call_args
        url_arg, payload_arg = args[0], args[1]
        assert isinstance(url_arg, str) and url_arg.startswith("https://hooks.slack.com/")
        from app.alerts.slack import SlackPayload
        assert isinstance(payload_arg, SlackPayload)
        assert payload_arg.source_name == "E2E Slack Source"
        assert payload_arg.metric == "latency_p95"
        assert payload_arg.value == 1234.0
        assert payload_arg.threshold == 500.0

    @pytest.mark.asyncio
    async def test_slack_dispatch_skips_when_no_url_configured(
        self, mock_slack_send, tenant_with_slack_source
    ):
        tenant, src = tenant_with_slack_source
        # Clear slack_webhook_url to simulate "no destination configured".
        async with AsyncSessionLocal() as session:
            s = await session.get(WebhookSource, src.id)
            s.alert_config = {}  # no slack_webhook_url
            await session.commit()

            rule = AnomalyRule(
                org_id=tenant.id, name="r2", rule_type=RULE_LATENCY_P95,
                threshold=1.0, window_seconds=60,
                workflow_id="wf-no-slack", enabled=True,
            )
            session.add(rule)
            await session.commit()
            await session.refresh(rule)
            event = AnomalyEvent(
                org_id=tenant.id, rule_id=rule.id, source_id=src.id,
                severity="low", message="x",
                context={"rule_type": "latency_p95"},
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)

            refreshed = await session.get(AnomalyEvent, event.id, populate_existing=True)
            results = await dispatch_slack_for_findings(
                session, [refreshed], notifier=SlackNotifier()
            )

        assert results == [False]
        assert mock_slack_send.await_count == 0


class TestRetryPipeline:
    """Failed event → ingest → manual retry → new retried event row."""

    @pytest.mark.asyncio
    async def test_failed_event_can_be_retried(
        self, client, mock_redis, mock_redis_rate_limit, mock_redis_pubsub, mock_celery_dispatch, seeded_source
    ):
        # 1) Ingest a failed event through the public webhook endpoint.
        event = _event_payload(workflow_id="wf-retry-1", status="error", run_id="run-orig")
        body = json.dumps(event).encode()
        signature = _sign(body, seeded_source.signing_secret)

        ingest = await client.post(
            f"/api/webhook/{seeded_source.id}",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hmac-signature": signature,
                "x-message-id": f"msg-{uuid.uuid4().hex[:8]}",
            },
        )
        assert ingest.status_code == 200, ingest.text
        assert mock_celery_dispatch.delay.called

        # 2) The Celery task is stubbed, so manually persist a failed
        #    workflow event row so the retry endpoint can find it.
        from datetime import datetime
        from app.models import WorkflowEvent
        original_id = uuid.uuid4()
        async with AsyncSessionLocal() as session:
            session.add(WorkflowEvent(
                id=original_id,
                source_id=seeded_source.id,
                workflow_id="wf-retry-1",
                run_id="run-orig",
                event_type="completed",
                status="error",
                payload=event,
                error_message="synthetic failure",
                duration_ms=5000,
                received_at=datetime.utcnow(),
            ))
            await session.commit()

        # 3) Trigger the manual retry.
        retry = await client.post(f"/api/events/{original_id}/retry")
        assert retry.status_code == 200, retry.text
        retry_data = retry.json()
        # The retry endpoint reports which new event was created.
        assert retry_data.get("status") == "retry_queued", retry_data
        assert "new_event_id" in retry_data or "retry_event_id" in retry_data

        # 4) The retry path scheduled a fresh Celery task.
        assert mock_celery_dispatch.delay.call_count >= 2  # original + retry

        # 5) The new event shows up in the listing.
        listed = await client.get(f"/api/events?source_id={seeded_source.id}")
        assert listed.status_code == 200
        items = listed.json()
        assert len(items) >= 2
        kinds = {item.get("event_type") for item in items}
        assert "completed" in kinds
        assert "retried" in kinds


class TestGitHubWebhookHealthE2E:
    """GitHub-platform webhook + health endpoint."""

    @pytest.mark.asyncio
    async def test_github_webhook_ingest_and_health(
        self,
        client,
        mock_redis,
        mock_redis_rate_limit,
        mock_redis_pubsub,
        mock_celery_dispatch,
        github_e2e_source,
    ):
        # Health check first.
        health = await client.get("/webhooks/github/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        payload = {
            "action": "completed",
            "workflow_run": {
                "id": 99999,
                "name": "E2E CI",
                "head_branch": "main",
                "conclusion": "success",
                "run_started_at": "2026-06-21T07:00:00Z",
                "updated_at": "2026-06-21T07:05:00Z",
                "run_number": 42,
            },
            "repository": {"full_name": github_e2e_source["repo"]},
            "sender": {"login": "octocat"},
        }
        body = json.dumps(payload).encode()
        sig = _sign(body, github_e2e_source["secret"])

        ingest = await client.post(
            "/webhooks/github",
            content=body,
            headers={"content-type": "application/json", "x-hub-signature-256": sig},
        )
        assert ingest.status_code == 200, ingest.text
        assert ingest.json().get("status") == "accepted"
        assert mock_celery_dispatch.delay.called

        # Health still green.
        health2 = await client.get("/webhooks/github/health")
        assert health2.status_code == 200
