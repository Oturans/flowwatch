"""Sprint 3: per-source configurable anomaly thresholds.

Adds a ``source_thresholds`` table that stores per-(source, metric)
overrides for anomaly detection. The engine looks these up at
evaluation time and prefers them over the hard-coded rule defaults.

Why a separate table? Threshold values are small (a handful of
floats per source) and read-heavy; the join cost on the existing
``webhook_sources.alert_config`` JSONB would be a lot higher for
``SELECT WHERE source_id = ? AND metric = ?`` queries. A dedicated
table also gives us Pydantic validation and indexed lookups.

The metrics enum is intentionally tight: only the three values the
Sprint 3 spec calls out (latency_ms, error_rate_pct, failure_count).
Adding a fourth is a one-line migration (``ALTER TABLE`` to extend
the CHECK) plus a new branch in the engine.

Revision ID: 005_source_thresholds
Revises: 004_traces_anomalies
Create Date: 2026-06-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "005_source_thresholds"
down_revision = "004_traces_anomalies"
branch_labels = None
depends_on = None


# Mirrored in ``app.models.observability.SourceThreshold`` so the
# ORM and the migration can't drift. The CHECK constraint at the DB
# level is the authoritative guard; the Python enum is convenience.
METRIC_LATENCY_MS = "latency_ms"
METRIC_ERROR_RATE_PCT = "error_rate_pct"
METRIC_FAILURE_COUNT = "failure_count"
VALID_METRICS = (METRIC_LATENCY_MS, METRIC_ERROR_RATE_PCT, METRIC_FAILURE_COUNT)


def upgrade() -> None:
    bind = op.get_bind()
    # Use a CHECK constraint to keep the metric set closed.
    # ``value`` is the threshold (units: ms, percent, count).
    # ``window_seconds`` is how far back to look when evaluating.
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS source_thresholds (
                id UUID PRIMARY KEY,
                source_id VARCHAR(64) NOT NULL REFERENCES webhook_sources(id) ON DELETE CASCADE,
                metric VARCHAR(32) NOT NULL,
                value DOUBLE PRECISION NOT NULL,
                window_seconds INTEGER NOT NULL DEFAULT 300,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT source_thresholds_metric_chk
                    CHECK (metric IN ('latency_ms', 'error_rate_pct', 'failure_count'))
            )
            """
        )
    )
    # One row per (source, metric). Allows updating in place.
    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_thresholds_source_metric "
            "ON source_thresholds (source_id, metric)"
        )
    )
    # Quick lookup by source.
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_source_thresholds_source "
            "ON source_thresholds (source_id)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_source_thresholds_source"))
    bind.execute(sa.text("DROP INDEX IF EXISTS uq_source_thresholds_source_metric"))
    bind.execute(sa.text("DROP TABLE IF EXISTS source_thresholds"))
