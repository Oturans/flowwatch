"""Sprint 3: alert dismiss support on anomaly_events.

Adds the columns we need to support the new alert history
acknowledge / dismiss workflow:

* ``severity`` already exists (string) — we just want to make sure
  the column is reachable via the dashboard filtering endpoint.
* ``status`` — derived state used by the dashboard: open | acknowledged
  | dismissed. Computed in the API layer from
  ``(acknowledged, dismissed)`` so the existing ``acknowledged`` /
  ``acknowledged_at`` / ``acknowledged_by`` columns stay untouched.
* ``dismissed`` (BOOLEAN) + ``dismissed_at`` (TIMESTAMPTZ) + 
  ``dismissed_by`` (VARCHAR(255)) — mirror of the ack columns.

The API exposes:
  PATCH /api/orgs/{org_id}/anomaly-events/{id}/ack  (already there)
  PATCH /api/orgs/{org_id}/anomaly-events/{id}/dismiss  (new)

The /api/v1/alerts unified history endpoint (Sprint 3) reads
``status`` from a derived expression so the schema doesn't have to
denormalize it.

Revision ID: 006_alert_dismiss
Revises: 005_source_thresholds
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "006_alert_dismiss"
down_revision = "005_source_thresholds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive: the column may already exist if a prior partial
    # migration ran. ``ADD COLUMN IF NOT EXISTS`` is supported in
    # Postgres 9.6+ which we're targeting.
    op.execute(
        "ALTER TABLE anomaly_events ADD COLUMN IF NOT EXISTS "
        "dismissed BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE anomaly_events ADD COLUMN IF NOT EXISTS "
        "dismissed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE anomaly_events ADD COLUMN IF NOT EXISTS "
        "dismissed_by VARCHAR(255)"
    )
    # Sprint 3: nullable source_id so we can join anomaly events
    # back to the webhook source that produced them. Older rows
    # (Sprint 2) have NULL; the dispatcher fills it in for new
    # events. We index it for the alert history filter.
    op.execute(
        "ALTER TABLE anomaly_events ADD COLUMN IF NOT EXISTS "
        "source_id VARCHAR(64)"
    )
    # The FK is added defensively (CREATE-only). Postgres doesn't
    # support ``ADD CONSTRAINT IF NOT EXISTS`` so we check
    # pg_constraint first.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'anomaly_events_source_id_fkey'
            ) THEN
                ALTER TABLE anomaly_events
                    ADD CONSTRAINT anomaly_events_source_id_fkey
                    FOREIGN KEY (source_id) REFERENCES webhook_sources(id)
                    ON DELETE SET NULL;
            END IF;
        END$$;
        """
    )
    # Index for the dashboard's "show me un-dismissed alerts" query.
    op.create_index(
        "ix_anomaly_events_org_dismissed",
        "anomaly_events",
        ["org_id", "dismissed"],
    )
    op.create_index(
        "ix_anomaly_events_source_detected",
        "anomaly_events",
        ["source_id", "detected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_anomaly_events_source_detected", table_name="anomaly_events")
    op.drop_index("ix_anomaly_events_org_dismissed", table_name="anomaly_events")
    op.drop_constraint("anomaly_events_source_id_fkey", "anomaly_events", type_="foreignkey")
    op.drop_column("anomaly_events", "source_id")
    op.drop_column("anomaly_events", "dismissed_by")
    op.drop_column("anomaly_events", "dismissed_at")
    op.drop_column("anomaly_events", "dismissed")
