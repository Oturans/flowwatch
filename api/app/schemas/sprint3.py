"""Pydantic schemas for Sprint 3 (thresholds + alerts v1).

Kept in a separate module from ``observability.py`` so the existing
Sprint 2 schemas don't get accidentally re-exported with the same
names. The v1 endpoints (under ``/api/v1/``) use these; the older
``/api/orgs/.../anomaly-events/.../ack`` endpoint keeps using the
Sprint 2 schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


#: Enum for the metric axis. ``latency_ms`` is in milliseconds,
#: ``error_rate_pct`` is percent (0-100), ``failure_count`` is a
#: positive integer count.
ThresholdMetric = Literal["latency_ms", "error_rate_pct", "failure_count"]


class ThresholdItem(BaseModel):
    """A single threshold row for a source.

    ``value`` carries the units implied by ``metric``:

    * ``latency_ms``      — milliseconds (>= 0)
    * ``error_rate_pct``  — percent, 0 <= value <= 100
    * ``failure_count``   — count, >= 0 (non-integer allowed for symmetry)
    """

    metric: ThresholdMetric
    value: float = Field(..., description="Threshold value (units depend on metric)")
    window_seconds: int = Field(300, ge=10, le=86400)
    enabled: bool = True

    @field_validator("value")
    @classmethod
    def _validate_value(cls, v: float, info) -> float:
        metric = info.data.get("metric") if hasattr(info, "data") else None
        if v < 0:
            raise ValueError("value must be >= 0")
        if metric == "error_rate_pct" and v > 100:
            raise ValueError("error_rate_pct must be in [0, 100]")
        return v


class ThresholdsUpdate(BaseModel):
    """Body for ``PATCH /api/v1/sources/{id}/thresholds``.

    Accepts a full list of metric/value pairs. Sending an empty
    list disables all thresholds for the source (engine falls back
    to the rule's own threshold).
    """

    thresholds: list[ThresholdItem] = Field(default_factory=list)

    @field_validator("thresholds")
    @classmethod
    def _no_duplicate_metrics(cls, v: list[ThresholdItem]) -> list[ThresholdItem]:
        seen: set[str] = set()
        for item in v:
            if item.metric in seen:
                raise ValueError(
                    f"duplicate metric '{item.metric}' in thresholds list"
                )
            seen.add(item.metric)
        return v


class ThresholdResponse(BaseModel):
    metric: ThresholdMetric
    value: float
    window_seconds: int
    enabled: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class ThresholdsResponse(BaseModel):
    source_id: str
    thresholds: list[ThresholdResponse]


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


class SlackConfigUpdate(BaseModel):
    """Body for ``POST /api/v1/sources/{id}/slack-config``.

    Set ``webhook_url`` to a Slack Incoming Webhook URL; pass
    ``enabled=False`` to keep the URL but suppress delivery.
    Set ``webhook_url`` to ``""`` (or null) to clear the config.
    """

    webhook_url: Optional[str] = Field(
        None,
        description=(
            "Slack Incoming Webhook URL. "
            "Pass an empty string to clear the configuration."
        ),
    )
    enabled: bool = True
    channel_hint: Optional[str] = Field(
        None,
        description=(
            "Optional human-friendly label (channel name, team, etc.) "
            "stored alongside the URL for display in the dashboard."
        ),
    )

    @field_validator("webhook_url")
    @classmethod
    def _validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return ""
        if not (v.startswith("https://hooks.slack.com/") or v.startswith("https://hooks.test.slack.com/")):
            # We accept any URL that starts with the Slack hooks host.
            # Anything else is almost certainly a misconfiguration and
            # we'd rather fail loudly than silently drop notifications.
            raise ValueError(
                "webhook_url must be a Slack Incoming Webhook "
                "(https://hooks.slack.com/...)"
            )
        return v


class SlackConfigResponse(BaseModel):
    source_id: str
    webhook_url_set: bool
    enabled: bool
    channel_hint: Optional[str] = None


# ---------------------------------------------------------------------------
# Alerts (v1)
# ---------------------------------------------------------------------------


#: Valid filter values for the ``status`` query param.
AlertStatusFilter = Literal["open", "acknowledged", "dismissed"]
AlertSeverityFilter = Literal["low", "medium", "high", "critical"]


class AlertListItem(BaseModel):
    """A single row in the ``GET /api/v1/alerts`` response.

    ``status`` is derived: ``open`` -> not acknowledged and not
    dismissed; ``acknowledged`` -> acknowledged; ``dismissed`` ->
    dismissed (and takes precedence over acknowledged when both
    are set).
    """

    id: uuid.UUID
    source_id: str
    source_name: Optional[str] = None
    rule_id: uuid.UUID
    rule_name: Optional[str] = None
    severity: str
    status: str
    message: str
    context: Optional[dict] = None
    detected_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    dismissed_at: Optional[datetime] = None
    dismissed_by: Optional[str] = None


class AlertListResponse(BaseModel):
    items: list[AlertListItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class AlertAckRequest(BaseModel):
    acknowledged_by: Optional[str] = Field(
        None, description="User identifier (email, name) to record"
    )


class AlertDismissRequest(BaseModel):
    dismissed_by: Optional[str] = Field(
        None, description="User identifier (email, name) to record"
    )


__all__ = [
    "ThresholdMetric",
    "ThresholdItem",
    "ThresholdsUpdate",
    "ThresholdResponse",
    "ThresholdsResponse",
    "SlackConfigUpdate",
    "SlackConfigResponse",
    "AlertStatusFilter",
    "AlertSeverityFilter",
    "AlertListItem",
    "AlertListResponse",
    "AlertAckRequest",
    "AlertDismissRequest",
]
