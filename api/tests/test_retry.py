"""
Tests for the manual retry endpoint: POST /api/events/{event_id}/retry

Coverage:
  - Successful retry records a new 'retried' event
  - Retry count is tracked via payload.retry_of chain
  - max_retries enforcement (both per-source and per-request override)
  - Non-retryable statuses are rejected (409)
  - Unknown event ids return 404
  - GET /api/sources/{source_id}/retry-config returns config
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


async def _insert_event(
    source_id: str,
    *,
    workflow_id: str = "wf-1",
    status: str = "error",
    run_id: str = "run-1",
    payload: dict | None = None,
):
    """Helper: insert a workflow event directly via the session factory."""
    from app.database import AsyncSessionLocal
    from app.models import WorkflowEvent

    eid = uuid.uuid4()
    ev = WorkflowEvent(
        id=eid,
        source_id=source_id,
        workflow_id=workflow_id,
        run_id=run_id,
        event_type="completed",
        status=status,
        payload=payload or {"a": 1},
        error_message="boom" if status == "error" else None,
        duration_ms=1234,
        received_at=datetime.utcnow(),
    )
    async with AsyncSessionLocal() as session:
        session.add(ev)
        await session.commit()
    return ev


@pytest.fixture
async def retry_source():
    """Source with retry config (max_retries=3, retryable statuses)."""
    from app.database import AsyncSessionLocal
    from app.models import WebhookSource

    sid = f"retry-{uuid.uuid4().hex[:8]}"
    src = WebhookSource(
        id=sid,
        name="Retry Source",
        signing_secret="retry-secret-1234",
        platform="n8n",
        alert_config={"max_retries": 3, "retry_on_status": ["error", "timeout"]},
        is_active=True,
    )
    async with AsyncSessionLocal() as session:
        session.add(src)
        await session.commit()
    return src


@pytest.fixture
def mock_celery_retry():
    with patch("app.tasks.tasks.process_event") as mock_task:
        mock_task.delay = MagicMock(return_value=None)
        yield mock_task


# ============== endpoint behaviour ==============


class TestRetryEndpoint:
    @pytest.mark.asyncio
    async def test_retry_failed_event(
        self, client, retry_source, mock_celery_retry
    ):
        original = await _insert_event(retry_source.id, status="error")

        response = await client.post(f"/api/events/{original.id}/retry")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "retry_queued"
        assert data["original_event_id"] == str(original.id)
        assert data["attempt"] == 1
        assert data["max_attempts"] == 3
        # A new event was recorded
        assert data["retry_event_id"] != str(original.id)
        # Celery was dispatched
        assert mock_celery_retry.delay.called

    @pytest.mark.asyncio
    async def test_retry_increments_attempt(
        self, client, retry_source, mock_celery_retry
    ):
        original = await _insert_event(retry_source.id, status="error")
        # First retry -> attempt 1
        r1 = await client.post(f"/api/events/{original.id}/retry")
        assert r1.status_code == 200
        assert r1.json()["attempt"] == 1
        # Second retry -> attempt 2
        r2 = await client.post(f"/api/events/{original.id}/retry")
        assert r2.status_code == 200
        assert r2.json()["attempt"] == 2

    @pytest.mark.asyncio
    async def test_retry_respects_max_retries(
        self, client, retry_source, mock_celery_retry
    ):
        original = await _insert_event(retry_source.id, status="error")
        # Use up the 3 attempts
        for i in range(1, 4):
            r = await client.post(f"/api/events/{original.id}/retry")
            assert r.status_code == 200, f"Attempt {i} failed: {r.text}"
            assert r.json()["attempt"] == i
        # 4th attempt should be rejected
        r = await client.post(f"/api/events/{original.id}/retry")
        assert r.status_code == 409
        assert "Max retries" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_retry_per_request_override_lowers_max(
        self, client, retry_source, mock_celery_retry
    ):
        original = await _insert_event(retry_source.id, status="error")
        # Override to 1 retry max
        r1 = await client.post(f"/api/events/{original.id}/retry?max_retries=1")
        assert r1.status_code == 200
        assert r1.json()["max_attempts"] == 1
        # Second attempt blocked
        r2 = await client.post(f"/api/events/{original.id}/retry?max_retries=1")
        assert r2.status_code == 409

    @pytest.mark.asyncio
    async def test_retry_rejects_success_status(
        self, client, retry_source, mock_celery_retry
    ):
        original = await _insert_event(retry_source.id, status="success")
        response = await client.post(f"/api/events/{original.id}/retry")
        assert response.status_code == 409
        assert "not retryable" in response.json()["detail"]
        assert not mock_celery_retry.delay.called

    @pytest.mark.asyncio
    async def test_retry_rejects_unknown_event(self, client, retry_source):
        fake_id = uuid.uuid4()
        response = await client.post(f"/api/events/{fake_id}/retry")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_rejects_non_uuid_id(self, client, retry_source):
        response = await client.post("/api/events/not-a-uuid/retry")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_records_event_type(
        self, client, retry_source, mock_celery_retry
    ):
        original = await _insert_event(retry_source.id, status="error")
        r = await client.post(f"/api/events/{original.id}/retry")
        assert r.status_code == 200
        # Verify the dispatched event is event_type='retried'
        call_args = mock_celery_retry.delay.call_args
        assert call_args is not None
        sent = call_args[0][0]
        assert sent["event_type"] == "retried"
        assert sent["status"] == "running"
        assert sent["retry_of"] == str(original.id)
        assert sent["retry_attempt"] == 1

    @pytest.mark.asyncio
    async def test_retry_config_endpoint(self, client, retry_source):
        r = await client.get(f"/api/sources/{retry_source.id}/retry-config")
        assert r.status_code == 200
        data = r.json()
        assert data["source_id"] == retry_source.id
        assert data["max_retries"] == 3
        assert "error" in data["retry_on_status"]

    @pytest.mark.asyncio
    async def test_retry_config_uses_defaults_when_unset(self, client):
        from app.database import AsyncSessionLocal
        from app.models import WebhookSource

        sid = f"no-cfg-{uuid.uuid4().hex[:8]}"
        src = WebhookSource(
            id=sid,
            name="No Config",
            signing_secret="defaultsecret-1234",
            platform="n8n",
            alert_config={},
            is_active=True,
        )
        async with AsyncSessionLocal() as session:
            session.add(src)
            await session.commit()

        r = await client.get(f"/api/sources/{sid}/retry-config")
        assert r.status_code == 200
        data = r.json()
        assert data["max_retries"] == 3
        # default retryable statuses
        assert "error" in data["retry_on_status"]
        assert "timeout" in data["retry_on_status"]
