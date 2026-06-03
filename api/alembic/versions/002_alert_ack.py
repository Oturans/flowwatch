"""Add escalation/ack columns to alert_log

Adds:
  - acknowledged_at (TIMESTAMPTZ NULL)
  - acknowledged_by  (VARCHAR(255) NULL)
  - escalated_at     (TIMESTAMPTZ NULL)

These power the P2 escalation flow: a Celery Beat task scans
unacknowledged alerts older than the per-source threshold and resends
the alert to the escalation recipients. Users acknowledge alerts via
``POST /api/alerts/{alert_id}/acknowledge`` which stamps
``acknowledged_at``.

Revision ID: 002_alert_ack
Revises: 001_initial
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "002_alert_ack"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alert_log",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alert_log",
        sa.Column("acknowledged_by", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "alert_log",
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index for the escalation Beat task: unacknowledged, by triggered_at.
    op.create_index(
        "idx_alertlog_status_triggered",
        "alert_log",
        ["status", "triggered_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_alertlog_status_triggered", table_name="alert_log")
    op.drop_column("alert_log", "escalated_at")
    op.drop_column("alert_log", "acknowledged_by")
    op.drop_column("alert_log", "acknowledged_at")
