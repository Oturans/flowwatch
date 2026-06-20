"""Sprint 4: trace spans (DAG nodes).

Adds a ``spans`` JSONB column to the ``traces`` table so the
ingestion endpoint can attach a list of child spans (the nodes of
the execution DAG) without forcing a separate table.

Each span is a dict shaped like::

    {
        "span_id":   "abc123",          # stable per-span id (required)
        "parent_id": null | "span_id",   # parent span in the same trace
        "name":      "llm.completion",  # user-visible label
        "status":    "ok" | "error" | ...,
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at":   "2026-01-01T00:00:01Z" | null,
        "duration_ms": 1000,
        "attributes": { ... },          # free-form
        "error_message": null | "..."
    }

The DAG is rendered client-side; we just persist the JSON. Keeping
spans inline (instead of a join table) is intentional: it lets the
dashboard hydrate a full trace in a single GET.

We also bump the limit on the ``status`` column to 32 chars on the
``traces`` table — the existing 16 is enough for the trace-level
status, but ``spans[].status`` and the dashboard filters reuse the
same vocabulary (``running``, ``ok``, ``error``, ``timeout``,
``cancelled``), so no widening is *strictly* required. Keeping the
trace.status column at 16 to remain backwards-compatible.

Revision ID: 007_trace_spans
Revises: 006_alert_dismiss
Create Date: 2026-06-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "007_trace_spans"
down_revision = "006_alert_dismiss"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # ``spans`` is an ordered JSONB array (preserving the order
    # clients sent). Default is an empty list so the column is
    # NOT NULL without breaking existing rows.
    bind.execute(
        sa.text(
            "ALTER TABLE traces "
            "ADD COLUMN IF NOT EXISTS spans JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
    )
    # GIN index for filtering by span attributes / status — keeps
    # the dashboard's "show me traces that contain at least one
    # failing span" query cheap.
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_traces_spans_gin ON traces USING gin (spans)")
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_traces_spans_gin"))
    bind.execute(sa.text("ALTER TABLE traces DROP COLUMN IF EXISTS spans"))