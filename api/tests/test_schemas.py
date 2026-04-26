import pytest
from app.schemas import (
    WebhookSourceCreate, WebhookSourceResponse,
    EventCreate, EventResponse, DashboardStats
)


class TestWebhookSourceSchemas:
    """Test webhook source schemas."""

    def test_source_create_valid(self):
        """Test valid source creation."""
        source = WebhookSourceCreate(
            id="test-source",
            name="Test Source",
            signing_secret="secret12345678",
            platform="n8n",
            alert_config={"slack": True}
        )
        assert source.id == "test-source"
        assert source.platform == "n8n"

    def test_source_create_minimal(self):
        """Test minimal source creation."""
        source = WebhookSourceCreate(
            id="minimal",
            name="Minimal",
            signing_secret="secret12345678",
            platform="make"
        )
        assert source.alert_config == {}

    def test_source_create_short_secret(self):
        """Test that short secrets are rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            WebhookSourceCreate(
                id="short",
                name="Short Secret",
                signing_secret="short",
                platform="n8n"
            )


class TestEventSchemas:
    """Test event schemas."""

    def test_event_create_valid(self):
        """Test valid event creation."""
        event = EventCreate(
            workflow_id="wf-123",
            run_id="run-456",
            event_type="completed",
            status="success",
            payload={"key": "value"},
            duration_ms=1500
        )
        assert event.workflow_id == "wf-123"
        assert event.status == "success"

    def test_event_create_minimal(self):
        """Test minimal event creation."""
        event = EventCreate(
            workflow_id="wf-123",
            event_type="started",
            status="running"
        )
        assert event.payload is None
        assert event.duration_ms is None

    def test_dashboard_stats(self):
        """Test dashboard stats schema."""
        stats = DashboardStats(
            total_events=1000,
            success_count=950,
            error_count=50,
            success_rate=95.0,
            active_sources=10,
            events_today=150
        )
        assert stats.total_events == 1000
        assert stats.success_rate == 95.0


class TestSchemaValidation:
    """Test schema validation edge cases."""

    def test_source_id_max_length(self):
        """Test source_id max length constraint."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            WebhookSourceCreate(
                id="a" * 65,  # 65 chars, max is 64
                name="Too Long",
                signing_secret="secret12345678",
                platform="n8n"
            )

    def test_workflow_id_max_length(self):
        """Test workflow_id max length constraint."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EventCreate(
                workflow_id="w" * 129,  # 129 chars, max is 128
                event_type="completed",
                status="success"
            )

    def test_negative_duration_rejected(self):
        """Test negative duration is rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EventCreate(
                workflow_id="wf-123",
                event_type="completed",
                status="success",
                duration_ms=-100
            )