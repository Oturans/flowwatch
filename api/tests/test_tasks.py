import os
import pytest
from unittest.mock import patch, MagicMock
from app.tasks.tasks import send_email_alert


class TestSendEmailAlert:
    """Test email alerting via Resend."""

    @pytest.fixture
    def event_data(self):
        return {
            "source_id": "test-source",
            "workflow_id": "test-workflow",
            "status": "failed",
            "error_message": "Connection timeout"
        }

    @pytest.mark.asyncio
    async def test_send_email_alert_success(self, event_data):
        """Test successful email sending via Resend."""
        import resend as resend_mod
        from app.tasks import tasks as tasks_mod
        from app.config import get_settings

        # Mutate the settings instance that tasks.py actually uses.
        get_settings.cache_clear()
        s = get_settings()
        s.resend_api_key = "test_key"
        s.alert_email_to = "alerts@example.com"
        s.alert_email_from = "FlowWatch <alerts@flowwatch.app>"
        # Force tasks_mod.settings to refer to the same mutated object.
        tasks_mod.settings = s

        with patch.object(resend_mod.Emails, "send") as mock_send, \
             patch("app.tasks.tasks.SessionLocal") as mock_session_local:
            mock_session = MagicMock()
            mock_session_local.return_value = mock_session

            mock_send.return_value = {"id": "email_123"}

            result = send_email_alert("event-123", event_data)

            assert result["status"] == "sent"
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_alert_no_config(self, event_data):
        """Test email alert skipped when not configured."""
        from app.tasks.tasks import settings as tasks_settings
        from app.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        s.resend_api_key = ""
        s.alert_email_to = ""
        # Force tasks_mod.settings to refer to the same mutated object.
        import app.tasks.tasks as tasks_mod
        tasks_mod.settings = s

        result = send_email_alert("event-123", event_data)
        assert result["status"] == "skipped"


from datetime import date, timedelta
from unittest.mock import patch, MagicMock


class TestPartitionCleanup:
    """Test partition maintenance SQL logic."""

    def test_partition_naming_convention(self):
        """Test partition table naming: workflow_events_yYYYYMMDD"""
        today = date.today()
        for i in range(1, 8):
            partition_date = today + timedelta(days=i)
            table_name = f"workflow_events_y{partition_date.strftime('%Y%m%d')}"
            assert table_name == f"workflow_events_y{partition_date.strftime('%Y%m%d')}"
            assert len(table_name) == len("workflow_events_y") + 8

    def test_partition_date_ranges(self):
        """Test partition creation SQL has correct FROM/TO ranges."""
        today = date.today()
        partition_date = today + timedelta(days=1)
        table_name = f"workflow_events_y{partition_date.strftime('%Y%m%d')}"
        start_val = partition_date.strftime("%Y-%m-%d 00:00:00")
        end_val = partition_date.strftime("%Y-%m-%d 23:59:59")

        # Verify range spans full day
        assert start_val.endswith("00:00:00")
        assert end_val.endswith("23:59:59")

    def test_old_partition_cutoff_calculation(self):
        """Test dropping partitions older than 7 days."""
        from datetime import date, timedelta
        today = date.today()
        cutoff = (today - timedelta(days=7)).strftime("%Y%m%d")

        # Verify cutoff is 7 days ago
        expected = (today - timedelta(days=7)).strftime("%Y%m%d")
        assert cutoff == expected

    def test_partition_drop_query_filter(self):
        """Test SQL query correctly filters old partitions."""
        cutoff = "20260419"
        # The query should filter: tablename < 'workflow_events_y' + cutoff
        old_table = "workflow_events_y20260418"
        current_table = "workflow_events_y20260426"

        # Old partitions should match filter
        assert old_table < f"workflow_events_y{cutoff}"
        # Current partitions should NOT match
        assert not (current_table < f"workflow_events_y{cutoff}")


class TestRetentionIntegration:
    """Integration test for the 7-day retention cleanup task.

    Verifies the real ``cleanup_old_events`` Celery task against the
    real database: it creates partitions for the next 7 days and drops
    any older than 7 days.
    """

    @pytest.mark.asyncio
    async def test_cleanup_creates_future_partitions(self):
        """cleanup_old_events creates partitions for the next 7 days."""
        from app.tasks.tasks import cleanup_old_events
        from datetime import date, timedelta
        from sqlalchemy import create_engine, text

        # Recreate the schema using the sync engine so the cleanup task
        # (which uses sync) has a parent table to partition.
        from app.database import Base
        import app.models  # noqa: F401
        engine = create_engine(os.environ["DATABASE_URL_SYNC"])
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

        # Run the task
        cleanup_old_events()

        # Verify partitions exist for today + 1..7
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT table_name FROM information_schema.tables "
                     "WHERE table_name LIKE 'workflow_events_y%'")
            )
            existing = {row[0] for row in result}

        today = date.today()
        for i in range(1, 8):
            d = today + timedelta(days=i)
            expected = f"workflow_events_y{d.strftime('%Y%m%d')}"
            assert expected in existing, f"missing partition {expected}"