"""Unit tests for the Sprint 3 Slack notifier.

Covers:

* Color mapping (severity -> hex)
* Metric formatter (latency_ms / error_rate_pct / failure_count)
* Block Kit message structure (required fields, color, blocks)
* SlackNotifier.send with a fake httpx client (success / failure)
* Redaction helper for logging
* payload_from_event lifts values out of AnomalyEvent.context
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.alerts.slack import (
    SEVERITY_COLORS,
    VALID_SEVERITIES,
    SlackNotifier,
    SlackPayload,
    build_slack_message,
    format_metric_human,
    payload_from_event,
    severity_color,
    _redact_url,
)


# ---------------------------------------------------------------------------
# Color mapping
# ---------------------------------------------------------------------------


class TestSeverityColor:
    def test_known_severities(self):
        assert severity_color("low") == "#36a64f"
        assert severity_color("medium") == "#daa038"
        assert severity_color("high") == "#d93025"
        assert severity_color("critical") == "#8b0000"

    def test_unknown_falls_back_to_amber(self):
        assert severity_color("nuclear") == SEVERITY_COLORS["medium"]
        assert severity_color("") == SEVERITY_COLORS["medium"]

    def test_case_insensitive(self):
        assert severity_color("HIGH") == "#d93025"
        assert severity_color("Medium") == "#daa038"

    def test_palette_has_all_severities(self):
        for sev in ("low", "medium", "high", "critical"):
            assert sev in SEVERITY_COLORS
        # VALID_SEVERITIES is the public contract.
        assert set(VALID_SEVERITIES) == {"low", "medium", "high", "critical"}


# ---------------------------------------------------------------------------
# Metric formatter
# ---------------------------------------------------------------------------


class TestFormatMetricHuman:
    def test_latency_ms_uses_integer(self):
        assert format_metric_human("latency_ms", 1234.0) == "1234 ms"
        assert format_metric_human("latency_p95", 999.6) == "1000 ms"

    def test_error_rate_uses_two_decimals(self):
        assert format_metric_human("error_rate_pct", 12.5) == "12.50%"
        assert format_metric_human("error_rate", 100.0) == "100.00%"

    def test_failure_count_label(self):
        assert format_metric_human("failure_count", 7) == "7 failures"
        assert format_metric_human("throughput_drop", 3) == "3 failures"

    def test_unknown_metric_falls_back(self):
        assert format_metric_human("custom_metric", 42.0) == "42.00"

    def test_empty_metric_does_not_crash(self):
        assert format_metric_human("", 1.0) == "1.00"


# ---------------------------------------------------------------------------
# Block Kit message
# ---------------------------------------------------------------------------


def _payload(**overrides) -> SlackPayload:
    base = dict(
        source_name="n8n-prod",
        metric="latency_ms",
        value=1234.0,
        threshold=500.0,
        severity="high",
        timestamp="2026-06-11T04:00:00+00:00",
        dashboard_url=None,
        workflow_id=None,
        rule_name=None,
        message=None,
    )
    base.update(overrides)
    return SlackPayload(**base)


class TestBuildSlackMessage:
    def test_minimum_message_shape(self):
        msg = build_slack_message(_payload())
        # Top-level keys
        assert "text" in msg
        assert "attachments" in msg
        assert "blocks" in msg
        # Single attachment, with the right color
        assert len(msg["attachments"]) == 1
        assert msg["attachments"][0]["color"] == "#d93025"
        # Block Kit header
        header = msg["blocks"][0]
        assert header["type"] == "header"
        assert "n8n-prod" in header["text"]["text"]

    def test_critical_severity_changes_emoji(self):
        msg = build_slack_message(_payload(severity="critical"))
        assert ":rotating_light:" in msg["blocks"][1]["text"]["text"]
        assert msg["attachments"][0]["color"] == "#8b0000"

    def test_workflow_id_appears_when_set(self):
        msg = build_slack_message(_payload(workflow_id="wf-42"))
        # The "fields" section is the third block.
        section = msg["blocks"][2]
        assert any("wf-42" in f["text"] for f in section["fields"])

    def test_rule_name_appears_when_set(self):
        msg = build_slack_message(_payload(rule_name="p95-too-high"))
        section = msg["blocks"][2]
        assert any("p95-too-high" in f["text"] for f in section["fields"])

    def test_dashboard_url_adds_action_button(self):
        msg = build_slack_message(_payload(dashboard_url="https://flowwatch.example/alerts/123"))
        # Last block should be an actions block.
        assert msg["blocks"][-1]["type"] == "actions"
        button = msg["blocks"][-1]["elements"][0]
        assert button["url"] == "https://flowwatch.example/alerts/123"

    def test_no_dashboard_url_omits_action(self):
        msg = build_slack_message(_payload(dashboard_url=None))
        assert all(b["type"] != "actions" for b in msg["blocks"])

    def test_message_included_in_section(self):
        msg = build_slack_message(_payload(message="p95 latency 1234ms exceeds threshold 500ms"))
        assert "1234ms exceeds threshold 500ms" in msg["blocks"][1]["text"]["text"]

    def test_fallback_text_present_and_concise(self):
        msg = build_slack_message(_payload())
        assert "n8n-prod" in msg["text"]
        assert "latency_ms" in msg["text"]
        assert "1234" in msg["text"]

    def test_message_serializes_to_json(self):
        # Ensure no non-serializable types snuck in (e.g. datetime).
        msg = build_slack_message(_payload())
        json.dumps(msg)  # must not raise

    def test_threshold_and_value_appear(self):
        msg = build_slack_message(_payload(metric="error_rate_pct", value=15.5, threshold=5.0))
        # The fields block lists them.
        section = msg["blocks"][2]
        field_texts = " ".join(f["text"] for f in section["fields"])
        assert "15.50%" in field_texts
        assert "5.00%" in field_texts


# ---------------------------------------------------------------------------
# SlackNotifier.send with a fake httpx client
# ---------------------------------------------------------------------------


def _fake_client(response: httpx.Response) -> MagicMock:
    """Build a fake httpx.AsyncClient context manager.

    The notifier uses ``async with client_factory(...) as client:`` and
    calls ``client.post``. The fake is a MagicMock whose ``__aenter__``
    returns a child mock with a ``post`` coroutine returning
    ``response``.
    """
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=None)
    cm.post = AsyncMock(return_value=response)
    return cm


def _response(status: int = 200, body: str = "ok") -> httpx.Response:
    return httpx.Response(status, text=body)


class TestSlackNotifierSend:
    @pytest.mark.asyncio
    async def test_send_2xx_returns_true(self):
        client = _fake_client(_response(200))
        notifier = SlackNotifier(client_factory=lambda **_: client)
        ok = await notifier.send(
            "https://hooks.slack.com/services/T/B/X",
            _payload(),
        )
        assert ok is True
        client.post.assert_awaited_once()
        args, kwargs = client.post.call_args
        assert args[0] == "https://hooks.slack.com/services/T/B/X"
        assert "json" in kwargs
        assert "text" in kwargs["json"]
        assert "attachments" in kwargs["json"]

    @pytest.mark.asyncio
    async def test_send_500_returns_false(self):
        client = _fake_client(_response(500, "internal"))
        notifier = SlackNotifier(client_factory=lambda **_: client)
        ok = await notifier.send("https://hooks.slack.com/x", _payload())
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_4xx_returns_false(self):
        client = _fake_client(_response(404))
        notifier = SlackNotifier(client_factory=lambda **_: client)
        ok = await notifier.send("https://hooks.slack.com/x", _payload())
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_network_error_returns_false(self):
        # Make the fake raise httpx.ConnectError.
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
        notifier = SlackNotifier(client_factory=lambda **_: client)
        ok = await notifier.send("https://hooks.slack.com/x", _payload())
        assert ok is False

    @pytest.mark.asyncio
    async def test_default_factory_works(self):
        """A real call should construct an httpx.AsyncClient.

        We point it at an invalid host to force a quick network
        error; we don't care about the outcome, only that the
        default path doesn't blow up on import-time wiring.
        """
        notifier = SlackNotifier()
        ok = await notifier.send(
            "https://invalid-host.invalid/x", _payload()
        )
        assert ok is False  # network error, but no exception


# ---------------------------------------------------------------------------
# payload_from_event
# ---------------------------------------------------------------------------


class TestPayloadFromEvent:
    def test_lifts_context_fields(self):
        detected = datetime(2026, 6, 11, 4, 0, 0, tzinfo=timezone.utc)
        event = SimpleNamespace(
            severity="high",
            message="p95 latency 1234ms exceeds threshold 500ms",
            detected_at=detected,
            context={
                "rule_type": "latency_p95",
                "metric_value": 1234.0,
                "threshold": 500.0,
            },
            rule=SimpleNamespace(
                name="p95-too-high",
                workflow_id="wf-42",
            ),
        )
        payload = payload_from_event(event, source_name="n8n-prod")
        assert payload.source_name == "n8n-prod"
        assert payload.metric == "latency_p95"
        assert payload.value == pytest.approx(1234.0)
        assert payload.threshold == pytest.approx(500.0)
        assert payload.severity == "high"
        assert payload.timestamp == "2026-06-11T04:00:00+00:00"
        assert payload.workflow_id == "wf-42"
        assert payload.rule_name == "p95-too-high"
        assert "p95 latency" in payload.message

    def test_handles_missing_context(self):
        event = SimpleNamespace(
            severity="medium",
            message="x",
            detected_at=None,
            context=None,
            rule=None,
        )
        payload = payload_from_event(event, source_name="src")
        assert payload.metric == "unknown"
        assert payload.value == 0.0
        assert payload.threshold == 0.0
        assert payload.workflow_id is None
        assert payload.timestamp == ""

    def test_severity_default_is_medium(self):
        event = SimpleNamespace(
            severity=None,
            message="",
            detected_at=None,
            context={},
            rule=None,
        )
        payload = payload_from_event(event, source_name="src")
        assert payload.severity == "medium"


# ---------------------------------------------------------------------------
# Redaction helper
# ---------------------------------------------------------------------------


class TestRedactUrl:
    def test_drops_secret_segment(self):
        url = "https://hooks.slack.com/services/T0/B0/secret"
        redacted = _redact_url(url)
        assert "secret" not in redacted
        assert "hooks.slack.com" in redacted

    def test_handles_empty(self):
        assert _redact_url("") == ""

    def test_handles_non_slack_url(self):
        assert _redact_url("https://example.com/foo/bar") == "https://example.com/foo/bar"
