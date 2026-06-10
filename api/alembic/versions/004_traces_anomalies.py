"""Sprint 2: traces + anomaly detection.

Adds three new tables:

* ``traces`` — top-level workflow / agent traces. The WebSocket
  ingestion endpoint writes to it; the dashboard reads from it.
  In environments where the TimescaleDB extension is installed,
  this is also converted to a hypertable partitioned by
  ``started_at`` for time-series analytics.
* ``anomaly_rules`` — per-tenant threshold rules for the engine.
* ``anomaly_events`` — when a rule fired, with a severity tag
  and a JSON context blob.

All tables are scoped to a tenant via ``org_id`` (FK to
``tenants``) so the multi-tenant RLS policies introduced in
Sprint 1 work out of the box.

Revision ID: 004_traces_anomalies
Revises: 003_tenants_users
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "004_traces_anomalies"
down_revision = "003_tenants_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------------
    # traces
    # ------------------------------------------------------------------------
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS traces (
                id UUID PRIMARY KEY,
                org_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                trace_id VARCHAR(128) NOT NULL,
                workflow_id VARCHAR(128),
                name VARCHAR(255) NOT NULL,
                source VARCHAR(64),
                status VARCHAR(16) NOT NULL DEFAULT 'ok',
                started_at TIMESTAMPTZ NOT NULL,
                ended_at TIMESTAMPTZ,
                duration_ms INTEGER,
                attributes JSONB,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_traces_org_started ON traces (org_id, started_at)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_traces_org_workflow ON traces (org_id, workflow_id)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_traces_org_status ON traces (org_id, status)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_traces_trace_id ON traces (trace_id)")
    )

    # Convert ``traces`` to a TimescaleDB hypertable. The helper
    # no-ops on plain Postgres (the test database doesn't have the
    # extension) and is idempotent on real Timescale installs.
    #
    # We use a brand-new, autocommit connection for the
    # hypertable work so it doesn't fight Alembic's transactional
    # DDL: the helper needs to issue ``CREATE EXTENSION`` (or
    # decide not to), and we don't want a failed ``CREATE EXTENSION
    # IF NOT EXISTS`` on a non-superuser DB to abort the rest of
    # the migration.
    try:
        from app.db.timescale import setup_hypertable_and_aggregate

        setup_hypertable_and_aggregate(
            table="traces",
            time_column="started_at",
            chunk_time_interval="1 hour",
            aggregate_name="traces_per_minute",
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        # Migration must not fail on plain Postgres; the table
        # already exists and the API works fine without the
        # hypertable conversion.
        import logging
        logging.getLogger(__name__).warning(
            "TimescaleDB setup skipped: %s", exc
        )

    # ------------------------------------------------------------------------
    # anomaly_rules
    # ------------------------------------------------------------------------
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS anomaly_rules (
                id UUID PRIMARY KEY,
                org_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                rule_type VARCHAR(32) NOT NULL,
                threshold DOUBLE PRECISION NOT NULL,
                window_seconds INTEGER NOT NULL DEFAULT 300,
                workflow_id VARCHAR(128),
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_anomaly_rules_org ON anomaly_rules (org_id)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_anomaly_rules_org_enabled ON anomaly_rules (org_id, enabled)")
    )

    # ------------------------------------------------------------------------
    # anomaly_events
    # ------------------------------------------------------------------------
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS anomaly_events (
                id UUID PRIMARY KEY,
                org_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                rule_id UUID NOT NULL REFERENCES anomaly_rules(id) ON DELETE CASCADE,
                detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                severity VARCHAR(16) NOT NULL DEFAULT 'medium',
                message TEXT NOT NULL,
                context JSONB,
                acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
                acknowledged_by VARCHAR(255),
                acknowledged_at TIMESTAMPTZ
            )
            """
        )
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_anomaly_events_org_detected ON anomaly_events (org_id, detected_at)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_anomaly_events_org_rule ON anomaly_events (org_id, rule_id)")
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_anomaly_events_org_rule"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_anomaly_events_org_detected"))
    bind.execute(sa.text("DROP TABLE IF EXISTS anomaly_events"))

    bind.execute(sa.text("DROP INDEX IF EXISTS ix_anomaly_rules_org_enabled"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_anomaly_rules_org"))
    bind.execute(sa.text("DROP TABLE IF EXISTS anomaly_rules"))

    bind.execute(sa.text("DROP INDEX IF EXISTS ix_traces_trace_id"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_traces_org_status"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_traces_org_workflow"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_traces_org_started"))
    bind.execute(sa.text("DROP TABLE IF EXISTS traces"))
