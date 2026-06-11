"""Sprint 3: Slack notifier for anomaly events.

Pure formatter + an async sender. The formatter builds a Slack
Block Kit message from an :class:`AnomalyEvent` and is unit
testable without any network. The sender wraps ``httpx.AsyncClient``
and is mockable.

The module is intentionally small. It does *not* know about the
database or the engine; the caller (the engine / API layer) hands
in a fully-built event and a webhook URL. This keeps the testing
surface tight and the failure modes obvious.

Color coding (per Slack Block Kit's ``color`` field on attachments
or the ``color`` keyword on the top-level block):

* low     -> ``#36a64f`` (green)
* medium  -> ``#daa038`` (amber)
* high    -> ``#d93025`` (red)
* critical-> ``#8b0000`` (deep red)

The default severity in the engine is ``medium``; ``high`` is used
when the metric exceeds 1.5x the threshold, ``critical`` is reserved
for "the system is on fire" cases (e.g. 100% error rate) but is not
yet produced by the engine — leaving the helper in place is cheap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------


SEVERITY_COLORS: dict[str, str] = {
    "low": "#36a64f",
    "medium": "#daa038",
    "high": "#d93025",
    "critical": "#8b0000",
}

VALID_SEVERITIES = tuple(SEVERITY_COLORS.keys())


def severity_color(severity: str) -> str:
    """Return the hex color for a severity bucket.

    Unknown severities fall back to amber so we never silently
    drop the color (Slack would otherwise show a black bar).
    """
    return SEVERITY_COLORS.get(severity.lower(), SEVERITY_COLORS["medium"])


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlackPayload:
    """Inputs the formatter needs.

    * ``source_name`` — human-readable source name (e.g. "n8n-prod").
    * ``metric``      — one of "latency_ms", "error_rate_pct",
      "failure_count", or the engine's own ``rule_type``
      (``latency_p95`` / ``error_rate`` / ``throughput_drop``).
    * ``value``       — observed metric value.
    * ``threshold``   — configured threshold the value was compared
      against (so the user can see "1234ms vs threshold 500ms").
    * ``severity``    — color bucket.
    * ``timestamp``   — ISO-8601 string. The engine produces UTC.
    * ``dashboard_url`` — link back to the alert in the dashboard.
    """

    source_name: str
    metric: str
    value: float
    threshold: float
    severity: str
    timestamp: str
    dashboard_url: Optional[str] = None
    workflow_id: Optional[str] = None
    rule_name: Optional[str] = None
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# Formatter (pure, no network)
# ---------------------------------------------------------------------------


def format_metric_human(metric: str, value: float) -> str:
    """Return a human-friendly string for a metric/value pair.

    Examples::

        >>> format_metric_human("latency_ms", 1234.0)
        '1234 ms'
        >>> format_metric_human("error_rate_pct", 12.5)
        '12.50%'
        >>> format_metric_human("failure_count", 7)
        '7 failures'
    """
    metric = (metric or "").lower()
    if metric in ("latency_ms", "latency_p95"):
        return f"{value:.0f} ms"
    if metric in ("error_rate_pct", "error_rate"):
        return f"{value:.2f}%"
    if metric in ("failure_count", "throughput_drop"):
        return f"{value:.0f} failures"
    # Fallback: just the number. Better than an opaque unit.
    return f"{value:.2f}"


def build_slack_message(payload: SlackPayload) -> dict[str, Any]:
    """Build a Slack Block Kit message (top-level dict).

    The structure is:

    * ``text`` — fallback for clients that don't render blocks.
    * ``attachments`` — a single attachment with a ``color`` bar
      that reflects the severity. The fields list surfaces the
      metric, threshold, source, and time.
    * ``blocks`` — header + section + actions (the latter is a
      single "Open in FlowWatch" link button when ``dashboard_url``
      is set).

    Slack accepts both ``blocks`` and the legacy ``attachments``
    shape; we send both so the message renders cleanly in older
    clients and the new ones.
    """
    color = severity_color(payload.severity)
    metric_display = format_metric_human(payload.metric, payload.value)
    threshold_display = format_metric_human(payload.metric, payload.threshold)

    headline = (
        f":warning: Anomaly detected on *{payload.source_name}*"
        if payload.severity != "critical"
        else f":rotating_light: CRITICAL anomaly on *{payload.source_name}*"
    )
    fallback = (
        f"[{payload.severity.upper()}] {payload.source_name}: "
        f"{payload.metric} = {metric_display} (threshold {threshold_display})"
    )

    # Block Kit: a header + a section with the key/value fields.
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": (
                    f"Anomaly: {payload.source_name}"
                    if payload.severity != "critical"
                    else f"CRITICAL: {payload.source_name}"
                ),
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{headline}\n{payload.message or ''}".rstrip(),
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Metric:*\n`{payload.metric}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Observed:*\n`{metric_display}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Threshold:*\n`{threshold_display}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Severity:*\n`{payload.severity}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Time:*\n`{payload.timestamp}`",
                },
            ],
        },
    ]
    if payload.workflow_id:
        blocks[2]["fields"].append(
            {
                "type": "mrkdwn",
                "text": f"*Workflow:*\n`{payload.workflow_id}`",
            }
        )
    if payload.rule_name:
        blocks[2]["fields"].append(
            {
                "type": "mrkdwn",
                "text": f"*Rule:*\n`{payload.rule_name}`",
            }
        )

    if payload.dashboard_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Open in FlowWatch",
                            "emoji": True,
                        },
                        "url": payload.dashboard_url,
                        "action_id": "open_in_flowwatch",
                    }
                ],
            }
        )

    return {
        "text": fallback,
        "attachments": [
            {
                "color": color,
                "blocks": blocks,
            }
        ],
        "blocks": blocks,
    }


# ---------------------------------------------------------------------------
# Sender (httpx; mockable in tests)
# ---------------------------------------------------------------------------


class SlackNotifier:
    """Thin wrapper around ``httpx.AsyncClient`` for Slack webhooks.

    Usage::

        notifier = SlackNotifier()
        ok = await notifier.send(webhook_url, payload)

    The constructor accepts an optional ``client_factory`` so tests
    can inject a fake. The default uses a short-timeout
    ``httpx.AsyncClient`` created per call (cheap because Slack
    webhook URLs are HTTPS and the call is one-shot).
    """

    def __init__(
        self,
        *,
        client_factory: Optional[Any] = None,
        timeout: float = 10.0,
    ):
        self._client_factory = client_factory
        self._timeout = timeout

    async def send(
        self,
        webhook_url: str,
        payload: SlackPayload,
    ) -> bool:
        """Post the formatted message to ``webhook_url``.

        Returns ``True`` on a 2xx response, ``False`` otherwise. We
        intentionally swallow non-2xx HTTP errors and return a bool
        rather than raising — the anomaly detection path should
        not crash just because Slack is down.
        """
        message = build_slack_message(payload)
        client_factory = self._client_factory or httpx.AsyncClient
        try:
            async with client_factory(timeout=self._timeout) as client:
                response = await client.post(webhook_url, json=message)
        except httpx.HTTPError as exc:
            logger.warning(
                "slack_send_failed url=%s err=%s",
                _redact_url(webhook_url),
                exc,
            )
            return False
        if response.status_code < 200 or response.status_code >= 300:
            logger.warning(
                "slack_non_2xx url=%s status=%s body=%s",
                _redact_url(webhook_url),
                response.status_code,
                response.text[:200] if response.text else "",
            )
            return False
        return True


def _redact_url(url: str) -> str:
    """Return a redacted version of a Slack webhook URL for logs.

    Slack webhooks look like
    ``https://hooks.slack.com/services/T0/B0/secret``. We keep the
    host and the service/team/channel IDs but drop the trailing
    secret token. This is enough to correlate logs without leaking
    the webhook into stdout.
    """
    if not url:
        return ""
    parts = url.rstrip("/").split("/")
    if len(parts) >= 3 and "slack.com" in url:
        # Drop the last segment (the secret) and the scheme.
        return "/".join(parts[:-1])
    return url


# ---------------------------------------------------------------------------
# Helper to build a payload from an AnomalyEvent
# ---------------------------------------------------------------------------


def payload_from_event(
    event: Any,
    *,
    source_name: str,
    dashboard_url: Optional[str] = None,
) -> SlackPayload:
    """Construct a :class:`SlackPayload` from an ``AnomalyEvent`` row.

    The ``event.context`` JSONB blob already carries ``metric_value``,
    ``rule_type``, and ``threshold`` thanks to
    :meth:`EvaluationResult.to_event`. We just lift them out.

    The rule-related fields (``rule_name``, ``workflow_id``) are
    read defensively: the caller should pre-load the rule
    relationship when possible. When the rule is unavailable
    (detached event after commit, or no rule in the test fixture)
    we fall back to ``None`` and use the rule_type from context
    for the human-readable metric label.
    """
    ctx: Mapping[str, Any] = event.context or {}
    metric = str(ctx.get("rule_type") or ctx.get("metric") or "unknown")
    value = float(ctx.get("metric_value") or 0.0)
    threshold = float(ctx.get("threshold") or 0.0)

    rule_name: Optional[str] = None
    workflow_id: Optional[str] = None
    # The caller can pass any object that quacks like an
    # ``AnomalyEvent`` (real ORM row, ``SimpleNamespace`` in tests,
    # etc.). We support two paths:
    #
    # 1. Real ORM row: ``sqlalchemy.inspect`` tells us whether the
    #    ``rule`` relationship is already loaded. If it is, use it;
    #    otherwise skip (a lazy load would block in async contexts).
    # 2. Plain object (e.g. ``SimpleNamespace``): ``getattr`` is
    #    safe because there is no descriptor to trigger a load.
    from sqlalchemy import inspect as _sa_inspect
    from sqlalchemy.orm import LoaderCallableStatus

    rule: Any = None
    try:
        insp = _sa_inspect(event)
        if "rule" in insp.attrs:
            lv = insp.attrs.rule.loaded_value
            if lv is not None and not isinstance(lv, LoaderCallableStatus):
                rule = lv
    except Exception:
        # Not a SQLAlchemy mapped object; fall back to ``getattr``.
        try:
            rule = getattr(event, "rule", None)
        except Exception:
            rule = None
    if rule is not None:
        try:
            rule_name = getattr(rule, "name", None)
            workflow_id = getattr(rule, "workflow_id", None)
        except Exception:
            rule_name = None
            workflow_id = None

    # We don't have a dedicated timestamp field on the SlackPayload
    # so we just stuff the ISO-formatted detected_at into the
    # ``timestamp`` slot.
    detected_at = getattr(event, "detected_at", None)
    timestamp = detected_at.isoformat() if detected_at else ""

    return SlackPayload(
        source_name=source_name,
        metric=metric,
        value=value,
        threshold=threshold,
        severity=str(getattr(event, "severity", "medium") or "medium"),
        timestamp=timestamp,
        dashboard_url=dashboard_url,
        workflow_id=workflow_id,
        rule_name=rule_name,
        message=str(getattr(event, "message", "") or ""),
    )


__all__ = [
    "SlackPayload",
    "SlackNotifier",
    "SEVERITY_COLORS",
    "VALID_SEVERITIES",
    "severity_color",
    "format_metric_human",
    "build_slack_message",
    "payload_from_event",
]
