"""
Tests for the GitHub-specific webhook endpoint: POST /webhooks/github

Coverage:
  - Signature verification (valid + invalid)
  - Payload normalisation (GitHub conclusion -> FlowWatch status)
  - Repository -> source mapping
  - End-to-end ingest (event is enqueued)
  - Error paths (invalid JSON, missing repo, unknown repo)
"""

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


SECRET = "github-webhook-secret-1234"
REPO = "Oturans/flowwatch"


def _sign(body: bytes) -> str:
    """Generate a valid X-Hub-Signature-256 for the body."""
    mac = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def _github_workflow_run_payload(
    *,
    conclusion: str = "success",
    repo: str = REPO,
    run_id: int = 12345,
    run_name: str = "CI",
    started: str = "2026-01-01T00:00:00Z",
    updated: str = "2026-01-01T00:05:00Z",
) -> dict:
    return {
        "action": "completed",
        "workflow_run": {
            "id": run_id,
            "name": run_name,
            "head_branch": "main",
            "conclusion": conclusion,
            "run_started_at": started,
            "updated_at": updated,
            "run_number": 7,
        },
        "repository": {"full_name": repo},
        "sender": {"login": "octocat"},
    }


@pytest.fixture
async def github_source():
    """Create a source configured for GitHub platform + repo mapping."""
    from app.database import AsyncSessionLocal
    from app.models import WebhookSource
    from sqlalchemy import delete

    sid = f"github-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(WebhookSource).where(WebhookSource.platform == "github")
        )
        await session.commit()

    src = WebhookSource(
        id=sid,
        name="FlowWatch GitHub",
        signing_secret=SECRET,
        platform="github",
        alert_config={"github_repo": REPO, "max_retries": 3},
        is_active=True,
    )
    async with AsyncSessionLocal() as session:
        session.add(src)
        await session.commit()
    return src


@pytest.fixture
def mock_celery_github():
    with patch("app.tasks.tasks.process_event") as mock_task:
        mock_task.delay = MagicMock(return_value=None)
        yield mock_task


# ============== signature helpers ==============


class TestGithubSignature:
    def test_valid_signature(self):
        from app.routes.github_webhooks import _verify_github_signature

        body = b'{"hello": "world"}'
        sig = _sign(body)
        assert _verify_github_signature(body, sig, SECRET) is True

    def test_wrong_signature(self):
        from app.routes.github_webhooks import _verify_github_signature

        body = b'{"hello": "world"}'
        bad = "sha256=" + "0" * 64
        assert _verify_github_signature(body, bad, SECRET) is False

    def test_missing_prefix(self):
        from app.routes.github_webhooks import _verify_github_signature

        body = b'{"hello": "world"}'
        sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        # No "sha256=" prefix should be rejected
        assert _verify_github_signature(body, sig, SECRET) is False

    def test_empty_signature(self):
        from app.routes.github_webhooks import _verify_github_signature

        assert _verify_github_signature(b"x", "", SECRET) is False


# ============== payload normalisation ==============


class TestGithubNormalisation:
    def test_success_conclusion(self):
        from app.routes.github_webhooks import _normalise_github_event

        event = _normalise_github_event(_github_workflow_run_payload(conclusion="success"))
        assert event["status"] == "success"
        assert event["error_message"] is None

    def test_failure_conclusion(self):
        from app.routes.github_webhooks import _normalise_github_event

        event = _normalise_github_event(_github_workflow_run_payload(conclusion="failure"))
        assert event["status"] == "error"
        assert "failure" in (event["error_message"] or "")

    def test_cancelled_conclusion(self):
        from app.routes.github_webhooks import _normalise_github_event

        event = _normalise_github_event(_github_workflow_run_payload(conclusion="cancelled"))
        assert event["status"] == "cancelled"

    def test_timed_out_conclusion(self):
        from app.routes.github_webhooks import _normalise_github_event

        event = _normalise_github_event(_github_workflow_run_payload(conclusion="timed_out"))
        assert event["status"] == "timeout"

    def test_duration_is_calculated(self):
        from app.routes.github_webhooks import _normalise_github_event

        # 5-minute run
        event = _normalise_github_event(_github_workflow_run_payload(
            started="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:05:00Z",
        ))
        assert event["duration_ms"] == 5 * 60 * 1000

    def test_run_id_is_stringified(self):
        from app.routes.github_webhooks import _normalise_github_event

        event = _normalise_github_event(_github_workflow_run_payload(run_id=9999))
        assert event["run_id"] == "7"  # run_number, not run_id

    def test_workflow_id_uses_run_id(self):
        from app.routes.github_webhooks import _normalise_github_event

        event = _normalise_github_event(_github_workflow_run_payload(run_id=42))
        assert event["workflow_id"] == "42"

    def test_invalid_timestamps_yield_null_duration(self):
        from app.routes.github_webhooks import _normalise_github_event

        event = _normalise_github_event(_github_workflow_run_payload(
            started="not-a-date",
            updated="also-not-a-date",
        ))
        assert event["duration_ms"] is None

    def test_unknown_conclusion_maps_to_unknown(self):
        from app.routes.github_webhooks import _normalise_github_event

        event = _normalise_github_event(_github_workflow_run_payload(conclusion="weird"))
        assert event["status"] == "unknown"


# ============== HTTP endpoint ==============


class TestGithubWebhookEndpoint:
    @pytest.mark.asyncio
    async def test_ingest_success(
        self, client, github_source, mock_celery_github
    ):
        payload = _github_workflow_run_payload(conclusion="success")
        body = json.dumps(payload).encode()
        response = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _sign(body),
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "accepted"
        assert "event_id" in data
        assert data["source_id"] == github_source.id
        # Celery was called
        assert mock_celery_github.delay.called

    @pytest.mark.asyncio
    async def test_ingest_failure(
        self, client, github_source, mock_celery_github
    ):
        payload = _github_workflow_run_payload(conclusion="failure")
        body = json.dumps(payload).encode()
        response = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _sign(body),
            },
        )
        assert response.status_code == 200
        # The dispatched event should carry status="error"
        call_args = mock_celery_github.delay.call_args
        assert call_args is not None
        sent_event = call_args[0][0]
        assert sent_event["status"] == "error"
        assert "failure" in (sent_event.get("error_message") or "")

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(
        self, client, github_source, mock_celery_github
    ):
        payload = _github_workflow_run_payload()
        body = json.dumps(payload).encode()
        response = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": "sha256=" + "0" * 64,
            },
        )
        assert response.status_code == 401
        assert "Invalid GitHub signature" in response.json()["detail"]
        assert not mock_celery_github.delay.called

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(
        self, client, github_source, mock_celery_github
    ):
        body = b"not valid json"
        response = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _sign(body),
            },
        )
        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_repo_returns_400(
        self, client, mock_celery_github
    ):
        payload = {"workflow_run": {"conclusion": "success"}}
        body = json.dumps(payload).encode()
        # No source exists for this payload; will be 400 (missing repo) before lookup
        response = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _sign(body),
            },
        )
        assert response.status_code == 400
        assert "repository.full_name" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_unknown_repo_returns_404(
        self, client, github_source, mock_celery_github
    ):
        payload = _github_workflow_run_payload(repo="nobody/nothing")
        body = json.dumps(payload).encode()
        response = await client.post(
            "/webhooks/github",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _sign(body),
            },
        )
        assert response.status_code == 404
        assert "No active source" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/webhooks/github/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["endpoint"] == "/webhooks/github"
