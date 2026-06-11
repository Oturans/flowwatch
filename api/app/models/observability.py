"""Sprint 2: traces + anomaly models.

Two new tables for the observability surface:

* ``traces`` — top-level workflow / agent traces pushed by clients
  over the WebSocket ingestion channel. Stores name, status, timing,
  and an arbitrary JSON ``attributes`` blob so callers can attach
  custom metadata (model name, prompt tokens, etc.).

* ``anomaly_rules`` — per-tenant threshold rules evaluated by the
  anomaly detection engine. The rule types are a small enum stored
  as a string so adding a new type is a non-breaking change.

* ``anomaly_events`` — fire-and-forget record of when a rule fired.
  Used both as a durable audit trail and as the data source for
  the dashboard's anomalies panel.

The Sprint 1 multi-tenant FK is reused: every row carries an
``org_id`` so the tenant middleware / RLS policies can scope reads.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


class Trace(Base):
    __tablename__ = "traces"
    __table_args__ = (
        Index("ix_traces_org_started", "org_id", "started_at"),
        Index("ix_traces_org_workflow", "org_id", "workflow_id"),
        Index("ix_traces_org_status", "org_id", "status"),
        Index("ix_traces_trace_id", "trace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attributes: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


# Rule types — kept as a small set of strings so the engine can
# dispatch on them. Adding a new detector means adding a constant
# here and a branch in the engine.
RULE_LATENCY_P95 = "latency_p95"
RULE_ERROR_RATE = "error_rate"
RULE_THROUGHPUT_DROP = "throughput_drop"
VALID_RULE_TYPES = (RULE_LATENCY_P95, RULE_ERROR_RATE, RULE_THROUGHPUT_DROP)


class AnomalyRule(Base):
    __tablename__ = "anomaly_rules"
    __table_args__ = (
        Index("ix_anomaly_rules_org", "org_id"),
        Index("ix_anomaly_rules_org_enabled", "org_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    workflow_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    events: Mapped[list["AnomalyEvent"]] = relationship(
        "AnomalyEvent", back_populates="rule", cascade="all, delete-orphan"
    )


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"
    __table_args__ = (
        Index("ix_anomaly_events_org_detected", "org_id", "detected_at"),
        Index("ix_anomaly_events_org_rule", "org_id", "rule_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("anomaly_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Sprint 3: nullable link back to the webhook source. Filled in
    # by the dispatcher so the alert history can join back to the
    # source name and Slack config. Older Sprint 2 events have NULL.
    source_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("webhook_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Sprint 3: dismiss workflow. The dashboard's "trash" button on an
    # alert sets ``dismissed=True`` so it stops showing in the default
    # alert list. ``acknowledged`` and ``dismissed`` are independent;
    # an acknowledged alert can still be dismissed later.
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dismissed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rule: Mapped["AnomalyRule"] = relationship("AnomalyRule", back_populates="events")


# ---------------------------------------------------------------------------
# Sprint 3: per-source configurable anomaly thresholds
# ---------------------------------------------------------------------------


# Metric enum kept as plain string constants so adding a fourth is a
# one-line migration (extend the CHECK + add a branch in the engine).
# Mirrored in the 005 migration's CHECK constraint.
METRIC_LATENCY_MS = "latency_ms"
METRIC_ERROR_RATE_PCT = "error_rate_pct"
METRIC_FAILURE_COUNT = "failure_count"
VALID_THRESHOLD_METRICS = (
    METRIC_LATENCY_MS,
    METRIC_ERROR_RATE_PCT,
    METRIC_FAILURE_COUNT,
)


class SourceThreshold(Base):
    """Per-source override for anomaly detection thresholds.

    Each row is a single (source_id, metric) tuple with the
    threshold value, evaluation window, and an enabled flag. The
    engine looks up the active row at evaluation time and prefers
    it over the hard-coded defaults baked into the rule objects.

    A unique index on (source_id, metric) keeps the cardinality at
    one row per metric, which makes PATCH updates a clean
    upsert. The API layer normalizes the request body into upserts
    via ``INSERT ... ON CONFLICT (source_id, metric) DO UPDATE``.
    """

    __tablename__ = "source_thresholds"
    __table_args__ = (
        # Mirrors the unique index created in migration 005.
        Index(
            "uq_source_thresholds_source_metric",
            "source_id",
            "metric",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("webhook_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Defensive guard used by the engine and the API layer.
def _coerce_uuid(value) -> uuid.UUID:
    """Coerce ``value`` to a UUID; raises ValueError on bad input."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# Re-export so the engine / API modules don't have to import the
# private helper. Anything that needs a ``uuid.UUID`` should use this.
normalize_uuid = _coerce_uuid


__all__ = [
    "Trace",
    "AnomalyRule",
    "AnomalyEvent",
    "SourceThreshold",
    "RULE_LATENCY_P95",
    "RULE_ERROR_RATE",
    "RULE_THROUGHPUT_DROP",
    "VALID_RULE_TYPES",
    "METRIC_LATENCY_MS",
    "METRIC_ERROR_RATE_PCT",
    "METRIC_FAILURE_COUNT",
    "VALID_THRESHOLD_METRICS",
    "normalize_uuid",
]
