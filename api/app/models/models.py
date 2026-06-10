import uuid
from datetime import datetime
from sqlalchemy import (
    String, Boolean, DateTime, Integer, Text, JSON, Index, ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class WebhookSource(Base):
    __tablename__ = "webhook_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    signing_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # 'n8n', 'make', 'custom'
    alert_config: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    events: Mapped[list["WorkflowEvent"]] = relationship("WorkflowEvent", back_populates="source")
    alerts: Mapped[list["AlertLog"]] = relationship("AlertLog", back_populates="source")


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        Index("idx_events_source_received", "source_id", "received_at"),
        Index("idx_events_workflow_received", "workflow_id", "received_at"),
        Index("idx_events_status_received", "status", "received_at"),
        {"postgresql_partition_by": "RANGE (received_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("webhook_sources.id"), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'started', 'completed', 'failed', 'retried'
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # 'success', 'error', 'running', 'timeout'
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=datetime.utcnow)

    source: Mapped["WebhookSource"] = relationship("WebhookSource", back_populates="events")


class AlertLog(Base):
    __tablename__ = "alert_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("webhook_sources.id"), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'email', 'slack'
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="sent")  # 'sent', 'failed', 'pending', 'acknowledged', 'escalated'
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Sprint 1: tenant scoping. The column is added nullable so the
    # 003 migration can backfill it before flipping the NOT NULL flag
    # on the next migration. For new installs the migration makes it
    # NOT NULL directly.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )

    source: Mapped["WebhookSource"] = relationship("WebhookSource", back_populates="alerts")