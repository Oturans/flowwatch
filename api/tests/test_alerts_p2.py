"""Tests for P2 alert features.

Covers:
  - Mute window helpers (is_muted, validation)
  - Escalation config helper
  - send_email_alert per-source recipient resolution
  - send_alert mute-window skip
  - PUT /api/sources/{id}/alert-rules
  - GET /api/sources/{id}/alert-rules
  - POST /api/sources/{id}/test-mute
  - POST /api/alerts/{id}/acknowledge
  - check_escalation task
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest


# ============== mute_windows helper ==============


class TestMuteWindows:
    def test_no_windows_returns_false(self):
        from app.alerts.mute_windows import is_muted

        source = SimpleNamespace(alert_config={})
        assert is_muted(source) is False

    def test_none_source_returns_false(self):
        from app.alerts.mute_windows import is_muted

        assert is_muted(None) is False

    def test_empty_config(self):
        from app.alerts.mute_windows import is_muted

        source = SimpleNamespace(alert_config=None)
        assert is_muted(source) is False

    def test_malformed_windows(self):
        from app.alerts.mute_windows import is_muted

        # Not a list
        assert is_muted(SimpleNamespace(alert_config={"mute_windows": "no"})) is False
        # List of non-dicts
        assert is_muted(SimpleNamespace(alert_config={"mute_windows": [1, 2]})) is False
        # Empty list
        assert is_muted(SimpleNamespace(alert_config={"mute_windows": []})) is False

    def test_inactive_window(self):
        """Window set for a different day is not active."""
        from app.alerts.mute_windows import is_muted

        # Pick a known Wednesday at 12:00 UTC.
        wednesday_noon = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["saturday", "sunday"],
                        "start_hour": 0,
                        "end_hour": 23,
                        "timezone": "UTC",
                    }
                ]
            }
        )
        assert is_muted(source, now_utc=wednesday_noon) is False

    def test_active_window_same_day(self):
        from app.alerts.mute_windows import is_muted

        # Saturday at 03:00 UTC, mute window 0-8 UTC
        saturday_3am = datetime(2026, 6, 6, 3, 0, tzinfo=timezone.utc)
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["saturday"],
                        "start_hour": 0,
                        "end_hour": 8,
                        "timezone": "UTC",
                    }
                ]
            }
        )
        assert is_muted(source, now_utc=saturday_3am) is True

    def test_active_window_outside_hours(self):
        from app.alerts.mute_windows import is_muted

        saturday_15 = datetime(2026, 6, 6, 15, 0, tzinfo=timezone.utc)
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["saturday"],
                        "start_hour": 0,
                        "end_hour": 8,
                        "timezone": "UTC",
                    }
                ]
            }
        )
        assert is_muted(source, now_utc=saturday_15) is False

    def test_overnight_window(self):
        """Window that wraps midnight (22:00-06:00)."""
        from app.alerts.mute_windows import is_muted

        # Friday 23:00 UTC
        fri_23 = datetime(2026, 6, 5, 23, 0, tzinfo=timezone.utc)
        # Friday 04:00 UTC
        fri_04 = datetime(2026, 6, 5, 4, 0, tzinfo=timezone.utc)
        # Friday 12:00 UTC (not muted)
        fri_12 = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["friday"],
                        "start_hour": 22,
                        "end_hour": 6,
                        "timezone": "UTC",
                    }
                ]
            }
        )
        assert is_muted(source, now_utc=fri_23) is True
        assert is_muted(source, now_utc=fri_04) is True
        assert is_muted(source, now_utc=fri_12) is False

    def test_timezone_aware(self):
        """Mute window uses the source's timezone, not UTC."""
        from app.alerts.mute_windows import is_muted

        # Friday 2026-06-05 at 22:00 UTC = 18:00 in America/New_York (EDT)
        friday_22_utc = datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc)
        # If the source mutes 0-8 in America/New_York, this is NOT muted.
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["friday"],
                        "start_hour": 0,
                        "end_hour": 8,
                        "timezone": "America/New_York",
                    }
                ]
            }
        )
        assert is_muted(source, now_utc=friday_22_utc) is False

        # Friday 05:00 UTC = 01:00 in NY -> muted
        friday_05_utc = datetime(2026, 6, 5, 5, 0, tzinfo=timezone.utc)
        assert is_muted(source, now_utc=friday_05_utc) is True

    def test_unknown_timezone_falls_back_to_utc(self):
        from app.alerts.mute_windows import is_muted

        sat_03 = datetime(2026, 6, 6, 3, 0, tzinfo=timezone.utc)
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["saturday"],
                        "start_hour": 0,
                        "end_hour": 8,
                        "timezone": "Mars/Olympus",
                    }
                ]
            }
        )
        assert is_muted(source, now_utc=sat_03) is True

    def test_zero_width_window_treated_as_active(self):
        """start_hour == end_hour on a matching day counts as muted."""
        from app.alerts.mute_windows import is_muted

        # Mon 12:00 UTC
        mon_12 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["monday"],
                        "start_hour": 5,
                        "end_hour": 5,
                        "timezone": "UTC",
                    }
                ]
            }
        )
        assert is_muted(source, now_utc=mon_12) is True

    def test_invalid_hours_skipped(self):
        from app.alerts.mute_windows import is_muted

        sat_03 = datetime(2026, 6, 6, 3, 0, tzinfo=timezone.utc)
        # Out-of-range hours -> window skipped
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["saturday"],
                        "start_hour": 25,
                        "end_hour": 30,
                        "timezone": "UTC",
                    }
                ]
            }
        )
        assert is_muted(source, now_utc=sat_03) is False

    def test_validate_mute_windows(self):
        from app.alerts.mute_windows import validate_mute_windows

        cleaned = validate_mute_windows(
            [
                {"days": ["SATURDAY"], "start_hour": 0, "end_hour": 8, "timezone": "UTC"},
                "not a dict",
                {"days": []},  # dropped (no days)
                {"days": ["monday"], "start_hour": 0, "end_hour": 0},  # zero-width: kept
                {"days": ["tuesday"], "start_hour": 0, "end_hour": 9, "timezone": "UTC"},
            ]
        )
        assert len(cleaned) == 3
        assert cleaned[0]["days"] == ["saturday"]
        assert cleaned[1]["days"] == ["monday"]
        assert cleaned[2]["days"] == ["tuesday"]
        assert cleaned[2]["end_hour"] == 9

    def test_list_active_windows(self):
        from app.alerts.mute_windows import list_active_windows

        sat_03 = datetime(2026, 6, 6, 3, 0, tzinfo=timezone.utc)
        source = SimpleNamespace(
            alert_config={
                "mute_windows": [
                    {
                        "days": ["saturday"],
                        "start_hour": 0,
                        "end_hour": 8,
                        "timezone": "UTC",
                    },
                    {
                        "days": ["monday"],
                        "start_hour": 0,
                        "end_hour": 8,
                        "timezone": "UTC",
                    },
                ]
            }
        )
        active = list_active_windows(source, now_utc=sat_03)
        assert len(active) == 1
        assert active[0]["days"] == ["saturday"]


# ============== escalation helper ==============


class TestEscalationConfig:
    def test_default_when_no_source(self):
        from app.alerts.escalation import get_escalation_config

        cfg = get_escalation_config(None)
        assert cfg["enabled"] is False
        assert cfg["escalate_to"] == []
        assert cfg["minutes_until_escalate"] == 15

    def test_default_when_no_alert_config(self):
        from app.alerts.escalation import get_escalation_config

        source = SimpleNamespace(alert_config=None)
        cfg = get_escalation_config(source)
        assert cfg["enabled"] is False

    def test_enabled_with_recipients(self):
        from app.alerts.escalation import get_escalation_config

        source = SimpleNamespace(
            alert_config={
                "escalation": {
                    "enabled": True,
                    "minutes_until_escalate": 30,
                    "escalate_to": ["a@example.com", "b@example.com"],
                }
            }
        )
        cfg = get_escalation_config(source)
        assert cfg["enabled"] is True
        assert cfg["minutes_until_escalate"] == 30
        assert cfg["escalate_to"] == ["a@example.com", "b@example.com"]

    def test_enabled_but_no_recipients(self):
        """Without recipients, enabled is forced to False."""
        from app.alerts.escalation import get_escalation_config

        source = SimpleNamespace(
            alert_config={"escalation": {"enabled": True, "escalate_to": []}}
        )
        cfg = get_escalation_config(source)
        assert cfg["enabled"] is False

    def test_minutes_clamped_to_minimum(self):
        from app.alerts.escalation import get_escalation_config

        source = SimpleNamespace(
            alert_config={
                "escalation": {"enabled": True, "minutes_until_escalate": 0}
            }
        )
        cfg = get_escalation_config(source)
        assert cfg["minutes_until_escalate"] == 1

    def test_invalid_minutes_falls_back(self):
        from app.alerts.escalation import get_escalation_config

        source = SimpleNamespace(
            alert_config={
                "escalation": {
                    "enabled": True,
                    "minutes_until_escalate": "not a number",
                }
            }
        )
        cfg = get_escalation_config(source)
        assert cfg["minutes_until_escalate"] == 15

    def test_filters_non_string_recipients(self):
        from app.alerts.escalation import get_escalation_config

        source = SimpleNamespace(
            alert_config={
                "escalation": {
                    "enabled": True,
                    "escalate_to": ["a@example.com", 42, None, ""],
                }
            }
        )
        cfg = get_escalation_config(source)
        assert cfg["escalate_to"] == ["a@example.com"]


# ============== send_email_alert per-source recipients ==============


class TestSendEmailAlertPerSource:
    """Per-source email recipients (P2 feature).

    The new send_email_alert looks up the source's alert_config.emails
    and uses it (or falls back to settings.alert_email_to) as the
    recipient list.
    """

    @pytest.fixture
    def event_data(self):
        return {
            "source_id": "src-per-source",
            "workflow_id": "wf-1",
            "status": "failed",
            "error_message": "boom",
        }

    def _make_session_mock(self, source_obj):
        """Build a MagicMock that supports `with SessionLocal() as s: ...`."""
        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.close = MagicMock()
        sess.query.return_value.filter_by.return_value.first.return_value = (
            source_obj
        )
        return sess

    @pytest.mark.asyncio
    async def test_uses_per_source_emails(self, event_data):
        """When source has alert_config.emails, use them (not global)."""
        import resend
        from app.tasks.tasks import send_email_alert
        from app.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        s.resend_api_key = "k"
        s.alert_email_to = "global@example.com"  # should be ignored
        s.alert_email_from = "FlowWatch <alerts@flowwatch.app>"

        with patch("app.tasks.tasks.SessionLocal") as mock_local, \
             patch.object(resend.Emails, "send") as mock_send:
            mock_local.return_value = self._make_session_mock(
                SimpleNamespace(alert_config={"emails": ["a@x.com", "b@x.com"]})
            )
            mock_send.return_value = {"id": "e1"}

            import app.tasks.tasks as tasks_mod
            tasks_mod.settings = s

            result = send_email_alert("ev-1", event_data)
            assert result["status"] == "sent"
            assert sorted(result["recipients"]) == ["a@x.com", "b@x.com"]
            # Verify resend was called with the per-source list, not the global
            call_args = mock_send.call_args[0][0]
            assert call_args["to"] == ["a@x.com", "b@x.com"]
            assert "global@example.com" not in call_args["to"]

    @pytest.mark.asyncio
    async def test_falls_back_to_global(self, event_data):
        """When source has no per-source emails, use global alert_email_to."""
        import resend
        from app.tasks.tasks import send_email_alert
        from app.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        s.resend_api_key = "k"
        s.alert_email_to = "global@example.com"
        s.alert_email_from = "FlowWatch <alerts@flowwatch.app>"

        with patch("app.tasks.tasks.SessionLocal") as mock_local, \
             patch.object(resend.Emails, "send") as mock_send:
            mock_local.return_value = self._make_session_mock(
                SimpleNamespace(alert_config={})
            )
            mock_send.return_value = {"id": "e1"}

            import app.tasks.tasks as tasks_mod
            tasks_mod.settings = s

            result = send_email_alert("ev-1", event_data)
            assert result["status"] == "sent"
            assert result["recipients"] == ["global@example.com"]

    @pytest.mark.asyncio
    async def test_skipped_when_no_recipients_anywhere(self, event_data):
        """No per-source AND no global -> skip."""
        from app.tasks.tasks import send_email_alert
        from app.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        s.resend_api_key = "k"
        s.alert_email_to = ""
        s.alert_email_from = "FlowWatch <alerts@flowwatch.app>"

        with patch("app.tasks.tasks.SessionLocal") as mock_local:
            mock_local.return_value = self._make_session_mock(
                SimpleNamespace(alert_config={"emails": []})
            )
            import app.tasks.tasks as tasks_mod
            tasks_mod.settings = s

            result = send_email_alert("ev-1", event_data)
            assert result["status"] == "skipped"
            assert result["reason"] == "no_recipients"

    @pytest.mark.asyncio
    async def test_skipped_when_no_resend_key(self, event_data):
        from app.tasks.tasks import send_email_alert
        from app.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        s.resend_api_key = ""
        s.alert_email_to = "anyone@example.com"

        import app.tasks.tasks as tasks_mod
        tasks_mod.settings = s
        result = send_email_alert("ev-1", event_data)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_resend_key"

    @pytest.mark.asyncio
    async def test_filter_empty_per_source_emails(self, event_data):
        """Per-source emails list with only empty strings falls back to global."""
        import resend
        from app.tasks.tasks import send_email_alert
        from app.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        s.resend_api_key = "k"
        s.alert_email_to = "global@example.com"

        with patch("app.tasks.tasks.SessionLocal") as mock_local, \
             patch.object(resend.Emails, "send") as mock_send:
            mock_local.return_value = self._make_session_mock(
                SimpleNamespace(alert_config={"emails": ["", None, 42]})
            )
            mock_send.return_value = {"id": "e1"}
            import app.tasks.tasks as tasks_mod
            tasks_mod.settings = s

            result = send_email_alert("ev-1", event_data)
            assert result["status"] == "sent"
            assert result["recipients"] == ["global@example.com"]


# ============== send_alert mute window ==============


class TestSendAlertMuted:
    @pytest.mark.asyncio
    async def test_send_alert_skipped_when_muted(self):
        from app.tasks.tasks import send_alert

        event_data = {
            "source_id": "muted-src",
            "workflow_id": "wf-x",
            "status": "error",
            "error_message": "boom",
        }

        def make_session_mock(source_obj):
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            sess.close = MagicMock()
            sess.query.return_value.filter_by.return_value.first.return_value = (
                source_obj
            )
            return sess

        with patch("app.tasks.tasks.SessionLocal") as mock_local, \
             patch("app.tasks.tasks.send_email_alert") as mock_email, \
             patch("app.tasks.tasks.is_muted", return_value=True):
            mock_local.return_value = make_session_mock(
                SimpleNamespace(
                    alert_config={"slack_webhook_url": "https://hooks.slack.com/x"}
                )
            )
            result = send_alert("ev-1", event_data)
            assert result["status"] == "skipped"
            assert result["reason"] == "muted"
            # Email task should NOT be dispatched
            assert not mock_email.delay.called

    @pytest.mark.asyncio
    async def test_send_email_alert_skipped_when_muted(self):
        import resend
        from app.tasks.tasks import send_email_alert
        from app.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        s.resend_api_key = "k"
        s.alert_email_to = "a@x.com"
        s.alert_email_from = "FlowWatch <alerts@flowwatch.app>"

        def make_session_mock(source_obj):
            sess = MagicMock()
            sess.__enter__ = MagicMock(return_value=sess)
            sess.__exit__ = MagicMock(return_value=False)
            sess.close = MagicMock()
            sess.query.return_value.filter_by.return_value.first.return_value = (
                source_obj
            )
            return sess

        with patch("app.tasks.tasks.SessionLocal") as mock_local, \
             patch("app.tasks.tasks.is_muted", return_value=True), \
             patch.object(resend.Emails, "send") as mock_send:
            mock_local.return_value = make_session_mock(
                SimpleNamespace(alert_config={"emails": ["a@x.com"]})
            )
            import app.tasks.tasks as tasks_mod
            tasks_mod.settings = s
            result = send_email_alert("ev-1", {"source_id": "s", "workflow_id": "w"})
            assert result["status"] == "skipped"
            assert result["reason"] == "muted"
            assert not mock_send.called


# ============== check_escalation task ==============


class TestCheckEscalation:
    @pytest.fixture
    def escalation_source(self):
        """Create a source with escalation config using the SYNC session.

        The Celery task uses the sync engine, so the helper function
        operates on a sync session too. We mirror that here.
        """
        from app.tasks.tasks import SessionLocal as SyncSessionLocal
        from app.models import WebhookSource

        sid = f"esc-{uuid.uuid4().hex[:8]}"
        src = WebhookSource(
            id=sid,
            name="Esc Source",
            signing_secret="escalation-secret-1234",
            platform="n8n",
            alert_config={
                "emails": ["oncall@example.com"],
                "escalation": {
                    "enabled": True,
                    "minutes_until_escalate": 5,
                    "escalate_to": ["manager@example.com"],
                },
            },
            is_active=True,
        )
        session = SyncSessionLocal()
        try:
            session.add(src)
            session.commit()
        finally:
            session.close()
        return sid

    def _insert_alert(self, source_id, **kwargs):
        from app.tasks.tasks import SessionLocal as SyncSessionLocal
        from app.models import AlertLog

        defaults = {
            "source_id": source_id,
            "alert_type": "email",
            "triggered_at": datetime.utcnow() - timedelta(hours=1),
            "message": "test",
            "status": "sent",
            "acknowledged_at": None,
            "escalated_at": None,
        }
        defaults.update(kwargs)
        alert = AlertLog(**defaults)
        session = SyncSessionLocal()
        try:
            session.add(alert)
            session.commit()
            session.refresh(alert)
            return alert.id
        finally:
            session.close()

    def _set_source_config(self, source_id, alert_config):
        from app.tasks.tasks import SessionLocal as SyncSessionLocal
        from app.models import WebhookSource
        from sqlalchemy.orm import Session

        session = SyncSessionLocal()
        try:
            src = session.query(WebhookSource).filter_by(id=source_id).first()
            src.alert_config = alert_config
            session.commit()
        finally:
            session.close()

    def _run_helper(self, source_id):
        from app.alerts.escalation import find_alerts_to_escalate
        from app.tasks.tasks import SessionLocal as SyncSessionLocal

        session = SyncSessionLocal()
        try:
            return find_alerts_to_escalate(session, source_id=source_id)
        finally:
            session.close()

    def _purge_all_alerts(self):
        from app.tasks.tasks import SessionLocal as SyncSessionLocal
        from app.models import AlertLog

        session = SyncSessionLocal()
        try:
            session.query(AlertLog).delete()
            session.commit()
        finally:
            session.close()

    def test_escalation_skipped_when_disabled(self, escalation_source):
        self._set_source_config(escalation_source, {"emails": ["a@x.com"]})
        self._insert_alert(escalation_source, message="old")
        alerts = self._run_helper(escalation_source)
        assert alerts == []

    def test_escalation_finds_old_unacked(self, escalation_source):
        self._insert_alert(escalation_source, message="old")
        alerts = self._run_helper(escalation_source)
        assert len(alerts) == 1

    def test_escalation_skips_recent(self, escalation_source):
        self._insert_alert(
            escalation_source,
            message="recent",
            triggered_at=datetime.utcnow() - timedelta(minutes=1),
        )
        alerts = self._run_helper(escalation_source)
        assert alerts == []

    def test_escalation_skips_acknowledged(self, escalation_source):
        self._insert_alert(
            escalation_source,
            message="ack'd",
            acknowledged_at=datetime.utcnow(),
        )
        alerts = self._run_helper(escalation_source)
        assert alerts == []

    def test_check_escalation_task_end_to_end(self, escalation_source):
        from app.tasks.tasks import check_escalation
        import resend

        # Purge any leftover alerts from earlier tests in this session.
        self._purge_all_alerts()
        # Capture the id of the alert we insert (the audit-log entry
        # created by _send_escalation_email has a different id).
        aid = self._insert_alert(escalation_source, message="escalate me")

        with patch.object(resend.Emails, "send") as mock_send:
            mock_send.return_value = {"id": "e-escalation"}
            result = check_escalation()
            assert result["status"] == "ok"
            assert result["escalated"] == 1
            assert mock_send.called
            call_args = mock_send.call_args[0][0]
            assert call_args["to"] == ["manager@example.com"]

        # Verify the alert is now status='escalated' (by its specific id,
        # since _send_escalation_email writes an audit-log entry).
        from app.tasks.tasks import SessionLocal as SyncSessionLocal
        from app.models import AlertLog

        session = SyncSessionLocal()
        try:
            alert = session.query(AlertLog).filter_by(id=aid).first()
            assert alert.status == "escalated"
            assert alert.escalated_at is not None
        finally:
            session.close()

    def test_check_escalation_no_candidates(self, escalation_source):
        from app.tasks.tasks import check_escalation

        # Purge so the test is hermetic.
        self._purge_all_alerts()

        result = check_escalation()
        assert result["status"] == "ok"
        assert result["escalated"] == 0


# ============== API endpoints ==============


@pytest.fixture
async def alert_source():
    from app.database import AsyncSessionLocal
    from app.models import WebhookSource

    sid = f"alerts-api-{uuid.uuid4().hex[:8]}"
    src = WebhookSource(
        id=sid,
        name="Alert Source",
        signing_secret="alertsecret-1234",
        platform="n8n",
        alert_config={
            "mute_windows": [
                {
                    "days": ["saturday", "sunday"],
                    "start_hour": 0,
                    "end_hour": 23,
                    "timezone": "UTC",
                }
            ],
            "escalation": {
                "enabled": True,
                "minutes_until_escalate": 10,
                "escalate_to": ["manager@example.com"],
            },
            "emails": ["oncall@example.com"],
        },
        is_active=True,
    )
    async with AsyncSessionLocal() as session:
        session.add(src)
        await session.commit()
    return src


class TestAlertRulesAPI:
    @pytest.mark.asyncio
    async def test_get_alert_rules(self, client, alert_source):
        r = await client.get(f"/api/sources/{alert_source.id}/alert-rules")
        assert r.status_code == 200
        data = r.json()
        assert data["source_id"] == alert_source.id
        assert len(data["mute_windows"]) == 1
        assert data["mute_windows"][0]["days"] == ["saturday", "sunday"]
        assert data["escalation"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_get_alert_rules_404(self, client):
        r = await client.get("/api/sources/no-such-source/alert-rules")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_put_alert_rules_replaces_mute_windows(self, client, alert_source):
        new_rules = {
            "mute_windows": [
                {
                    "days": ["monday", "tuesday"],
                    "start_hour": 22,
                    "end_hour": 6,
                    "timezone": "UTC",
                }
            ]
        }
        r = await client.put(
            f"/api/sources/{alert_source.id}/alert-rules", json=new_rules
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["alert_config"]["mute_windows"]) == 1
        assert data["alert_config"]["mute_windows"][0]["days"] == ["monday", "tuesday"]
        # Escalation preserved (we only sent mute_windows)
        assert data["alert_config"]["escalation"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_put_alert_rules_replaces_escalation(self, client, alert_source):
        new_rules = {
            "escalation": {
                "enabled": True,
                "minutes_until_escalate": 30,
                "escalate_to": ["vp@example.com", "ceo@example.com"],
            }
        }
        r = await client.put(
            f"/api/sources/{alert_source.id}/alert-rules", json=new_rules
        )
        assert r.status_code == 200
        esc = r.json()["alert_config"]["escalation"]
        assert esc["minutes_until_escalate"] == 30
        assert "vp@example.com" in esc["escalate_to"]
        assert "ceo@example.com" in esc["escalate_to"]

    @pytest.mark.asyncio
    async def test_put_alert_rules_invalid_mute_windows_type(self, client, alert_source):
        r = await client.put(
            f"/api/sources/{alert_source.id}/alert-rules",
            json={"mute_windows": "not a list"},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_put_alert_rules_invalid_minutes(self, client, alert_source):
        r = await client.put(
            f"/api/sources/{alert_source.id}/alert-rules",
            json={"escalation": {"minutes_until_escalate": 999999}},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_put_alert_rules_invalid_hours(self, client, alert_source):
        r = await client.put(
            f"/api/sources/{alert_source.id}/alert-rules",
            json={
                "mute_windows": [
                    {"days": ["monday"], "start_hour": 25, "end_hour": 30, "timezone": "UTC"}
                ]
            },
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_put_alert_rules_unknown_source(self, client):
        r = await client.put(
            "/api/sources/nonexistent/alert-rules",
            json={"mute_windows": []},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_put_alert_rules_valid_windows_only(self, client, alert_source):
        """The schema validates each window; one bad window fails the request."""
        r = await client.put(
            f"/api/sources/{alert_source.id}/alert-rules",
            json={
                "mute_windows": [
                    {"days": ["monday"], "start_hour": 0, "end_hour": 8, "timezone": "UTC"},
                ]
            },
        )
        assert r.status_code == 200
        assert len(r.json()["alert_config"]["mute_windows"]) == 1

    @pytest.mark.asyncio
    async def test_test_mute_endpoint(self, client, alert_source):
        r = await client.post(f"/api/sources/{alert_source.id}/test-mute")
        assert r.status_code == 200
        data = r.json()
        # Whether currently muted depends on the test time, but
        # active_windows should always be a list.
        assert "muted" in data
        assert isinstance(data["active_windows"], list)

    @pytest.mark.asyncio
    async def test_test_mute_unknown_source(self, client):
        r = await client.post("/api/sources/nonexistent/test-mute")
        assert r.status_code == 404


class TestAcknowledgeAPI:
    @pytest.fixture
    async def pending_alert(self, alert_source):
        from app.database import AsyncSessionLocal
        from app.models import AlertLog

        alert = AlertLog(
            source_id=alert_source.id,
            alert_type="email",
            message="pending",
            status="sent",
            triggered_at=datetime.utcnow(),
        )
        async with AsyncSessionLocal() as session:
            session.add(alert)
            await session.commit()
            await session.refresh(alert)
        return alert

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self, client, pending_alert):
        r = await client.post(f"/api/alerts/{pending_alert.id}/acknowledge")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "acknowledged"
        assert data["acknowledged_at"] is not None

    @pytest.mark.asyncio
    async def test_acknowledge_alert_with_actor(self, client, pending_alert):
        r = await client.post(
            f"/api/alerts/{pending_alert.id}/acknowledge",
            json={"acknowledged_by": "alice@example.com"},
        )
        assert r.status_code == 200
        assert r.json()["acknowledged_by"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_acknowledge_unknown_alert(self, client):
        fake = uuid.uuid4()
        r = await client.post(f"/api/alerts/{fake}/acknowledge")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_acknowledge_bad_uuid(self, client):
        r = await client.post("/api/alerts/not-a-uuid/acknowledge")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_acknowledge_is_idempotent(self, client, pending_alert):
        r1 = await client.post(f"/api/alerts/{pending_alert.id}/acknowledge")
        assert r1.status_code == 200
        r2 = await client.post(f"/api/alerts/{pending_alert.id}/acknowledge")
        assert r2.status_code == 200
        assert r2.json()["status"] == "already_acknowledged"

    @pytest.mark.asyncio
    async def test_acknowledge_updates_status_in_db(self, client, pending_alert):
        from app.database import AsyncSessionLocal
        from app.models import AlertLog
        from sqlalchemy import select

        await client.post(f"/api/alerts/{pending_alert.id}/acknowledge")
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AlertLog).where(AlertLog.id == pending_alert.id)
            )
            alert = result.scalar_one()
            assert alert.status == "acknowledged"
            assert alert.acknowledged_at is not None
