import pytest
import json
import hmac
import hashlib
import asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from app.main import app
from app.config import get_settings

settings = get_settings()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    with patch("app.routes.webhooks.redis_client") as mock:
        mock.get = AsyncMock(return_value=None)
        mock.setex = AsyncMock(return_value=True)
        mock.incr = AsyncMock(return_value=1)
        mock.lpush = AsyncMock(return_value=1)
        mock.publish = AsyncMock(return_value=1)
        yield mock


@pytest.fixture
def mock_redis_rate_limit():
    """Mock Redis rate limit client."""
    with patch("app.routes.webhooks.redis_rate_limit") as mock:
        mock.get = AsyncMock(return_value=None)
        mock.setex = AsyncMock(return_value=True)
        mock.incr = AsyncMock(return_value=1)
        yield mock


@pytest.fixture
def mock_celery():
    """Mock Celery task dispatch so tests don't need a real broker."""
    with patch("app.tasks.tasks.process_event") as mock_task:
        mock_task.delay = MagicMock(return_value=None)
        yield mock_task


def create_hmac_signature(body: bytes, secret: str) -> str:
    """Create HMAC-SHA256 signature."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={expected}"


class TestWebhookIngestion:
    """Test webhook ingestion endpoint."""

    @pytest.mark.asyncio
    async def test_webhook_ingest_valid(self, client, mock_redis, mock_redis_rate_limit, mock_celery, seeded_source):
        """Test valid webhook ingestion."""
        event_data = {
            "workflow_id": "wf-123",
            "run_id": "run-456",
            "event_type": "completed",
            "status": "success",
            "payload": {"test": "data"}
        }
        body = json.dumps(event_data).encode()
        signature = create_hmac_signature(body, seeded_source.signing_secret)

        response = await client.post(
            "/api/webhook/test-source",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hmac-signature": signature,
                "x-message-id": "test-msg-001",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "event_id" in data

    @pytest.mark.asyncio
    async def test_webhook_ingest_missing_workflow_id(self, client, mock_redis, mock_redis_rate_limit, mock_celery, seeded_source):
        """Test webhook rejection when workflow_id is missing."""
        event_data = {
            "run_id": "run-456",
            "status": "success"
        }
        body = json.dumps(event_data).encode()
        signature = create_hmac_signature(body, seeded_source.signing_secret)

        response = await client.post(
            "/api/webhook/test-source",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hmac-signature": signature,
            },
        )

        assert response.status_code == 400
        assert "workflow_id" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_webhook_ingest_invalid_json(self, client, mock_redis, mock_redis_rate_limit, mock_celery, seeded_source):
        """Test webhook rejection for invalid JSON."""
        body = b"not valid json"
        signature = create_hmac_signature(body, seeded_source.signing_secret)

        response = await client.post(
            "/api/webhook/test-source",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hmac-signature": signature,
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_rate_limit_exceeded(self, client, mock_redis, mock_redis_rate_limit, mock_celery, seeded_source):
        """Test rate limiting."""
        # Mock rate limit to return max
        mock_redis_rate_limit.get = AsyncMock(return_value="100")

        event_data = {"workflow_id": "wf-123", "status": "success"}
        body = json.dumps(event_data).encode()
        signature = create_hmac_signature(body, seeded_source.signing_secret)

        response = await client.post(
            "/api/webhook/test-source",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hmac-signature": signature,
            },
        )

        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_webhook_replay_protection(self, client, mock_redis, mock_redis_rate_limit, mock_celery, seeded_source):
        """Test replay protection for duplicate messages."""
        # Mock that message_id was already seen
        mock_redis.get = AsyncMock(return_value="1")

        event_data = {"workflow_id": "wf-123", "status": "success"}
        body = json.dumps(event_data).encode()
        signature = create_hmac_signature(body, seeded_source.signing_secret)

        response = await client.post(
            "/api/webhook/test-source",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hmac-signature": signature,
                "x-message-id": "duplicate-msg",
            },
        )

        # Should still return 200 but indicate duplicate
        assert response.status_code == 200
        data = response.json()
        assert data.get("duplicate") is True


class TestCRUDAPI:
    """Test CRUD API endpoints."""

    @pytest.mark.asyncio
    async def test_list_sources_empty(self, client):
        """Test listing sources when empty."""
        response = await client.get("/api/sources")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_create_source(self, client):
        """Test creating a new webhook source."""
        source_data = {
            "id": "test-source-001",
            "name": "Test Source",
            "signing_secret": "supersecret123",
            "platform": "n8n",
            "alert_config": {"slack_webhook_url": "https://hooks.slack.com/test"}
        }

        response = await client.post("/api/sources", json=source_data)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-source-001"
        assert data["name"] == "Test Source"

    @pytest.mark.asyncio
    async def test_create_duplicate_source(self, client):
        """Test creating duplicate source fails."""
        source_data = {
            "id": "dup-source",
            "name": "Duplicate",
            "signing_secret": "secret-12345",
            "platform": "n8n"
        }

        # Create first
        response = await client.post("/api/sources", json=source_data)
        assert response.status_code == 200, response.text

        # Try to create duplicate
        response = await client.post("/api/sources", json=source_data)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_source(self, client):
        """Test getting a specific source."""
        # Create source first
        source_data = {
            "id": "get-test-source",
            "name": "Get Test",
            "signing_secret": "secret-12345",
            "platform": "make"
        }
        r = await client.post("/api/sources", json=source_data)
        assert r.status_code == 200, r.text

        # Get source
        response = await client.get("/api/sources/get-test-source")
        assert response.status_code == 200
        assert response.json()["id"] == "get-test-source"

    @pytest.mark.asyncio
    async def test_get_source_not_found(self, client):
        """Test getting non-existent source."""
        response = await client.get("/api/sources/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_source(self, client):
        """Test updating a source."""
        # Create source
        source_data = {
            "id": "update-test-source",
            "name": "Original Name",
            "signing_secret": "secret-12345",
            "platform": "n8n"
        }
        r = await client.post("/api/sources", json=source_data)
        assert r.status_code == 200, r.text

        # Update
        response = await client.patch(
            "/api/sources/update-test-source",
            json={"name": "Updated Name"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_source(self, client):
        """Test deleting a source."""
        # Create source
        source_data = {
            "id": "delete-test-source",
            "name": "Delete Me",
            "signing_secret": "secret-12345",
            "platform": "custom"
        }
        r = await client.post("/api/sources", json=source_data)
        assert r.status_code == 200, r.text

        # Delete
        response = await client.delete("/api/sources/delete-test-source")
        assert response.status_code == 200

        # Verify deleted
        response = await client.get("/api/sources/delete-test-source")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_events_empty(self, client):
        """Test listing events when empty."""
        response = await client.get("/api/events")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_list_events_with_filters(self, client):
        """Test listing events with filters."""
        response = await client.get(
            "/api/events",
            params={"source_id": "test", "status": "success", "limit": 10}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_dashboard_stats(self, client):
        """Test dashboard stats endpoint."""
        response = await client.get("/api/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_events" in data
        assert "success_rate" in data
        assert "active_sources" in data


class TestSSE:
    """Test SSE endpoint.

    The endpoint streams forever so we don't consume the stream in tests;
    we just verify the route is registered and not conflicting with
    /api/events/{event_id}.
    """

    @pytest.mark.asyncio
    async def test_event_stream_endpoint_path(self, client):
        """Verify SSE path resolves and is registered."""
        from app.main import app
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/stream/events" in paths

    @pytest.mark.asyncio
    async def test_sse_does_not_conflict_with_event_detail(self, client):
        """/api/events/{event_id} should not match /api/stream/events."""
        # A bad UUID hits the event-detail route, not the SSE route.
        # Confirm by checking we get 404 with a JSON body, not an SSE stream.
        r = await client.get("/api/events/not-a-uuid")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")


class TestHealthCheck:
    """Test health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        """Test main health endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_api_health(self, client):
        """Test API health endpoint."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "FlowWatch API"
        assert "version" in data