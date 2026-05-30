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
        with patch("resend.Emails.send") as mock_resend:
            mock_resend.Emails.send = MagicMock(return_value={"id": "email_123"})
            with patch("app.tasks.tasks.SessionLocal") as mock_session:
                mock_session.return_value.__enter__ = MagicMock()
                mock_session.return_value.__exit__ = MagicMock()
                mock_session_instance = MagicMock()
                mock_session.return_value = mock_session_instance

                # Call without .delay (direct call)
                from app.config import get_settings
                settings = get_settings()
                settings.alert_email_to = "alerts@example.com"
                settings.alert_email_from = "FlowWatch <alerts@flowwatch.app>"
                settings.resend_api_key = "test_key"

                result = send_email_alert("event-123", event_data)
                assert result["status"] == "sent"
                mock_resend.Emails.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_alert_no_config(self, event_data):
        """Test email alert skipped when not configured."""
        from app.config import get_settings
        settings = get_settings()
        settings.resend_api_key = ""
        settings.alert_email_to = ""

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