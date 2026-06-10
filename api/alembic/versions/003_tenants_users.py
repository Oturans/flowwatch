"""Sprint 1: tenants, users, org_id on alert_log.

Creates the multi-tenant schema:

* ``tenants`` — organizations; one tenant per FlowWatch customer.
* ``users``   — accounts scoped to a tenant via ``org_id``.
* ``alert_log.org_id`` — backfilled from the FIRST tenant created in
  this migration. Existing rows are stamped with that tenant; new rows
  require ``org_id`` going forward.

The migration is idempotent-friendly: it uses ``CREATE TABLE IF NOT
EXISTS`` for tenants and users, and ``IF NOT EXISTS`` for the new
``org_id`` column. A default tenant is created on first install so
that legacy data (which has no tenant) can be assigned somewhere.

Revision ID: 003_tenants_users
Revises: 002_alert_ack
Create Date: 2026-06-10
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "003_tenants_users"
down_revision = "002_alert_ack"
branch_labels = None
depends_on = None


# A sentinel UUID used as the legacy "default" tenant id. We pick a
# deterministic value so multiple runs of the migration on the same
# database don't create duplicate default tenants.
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Default Tenant"


def _create_default_tenant(bind) -> uuid.UUID:
    """Insert the default tenant if it doesn't exist; return its id.

    Helper for the backfill of ``alert_log.org_id``. The function
    uses the provided Alembic ``bind`` to talk to the database.
    """
    # ``sa.inspect`` is sync and works on both PostgreSQL and SQLite.
    inspector = sa.inspect(bind)
    if "tenants" not in inspector.get_table_names():
        return DEFAULT_TENANT_ID

    existing = bind.execute(
        sa.text("SELECT id FROM tenants WHERE slug = :slug"),
        {"slug": DEFAULT_TENANT_SLUG},
    ).first()
    if existing:
        return existing[0]

    bind.execute(
        sa.text(
            """
            INSERT INTO tenants (id, name, slug, plan, is_active, created_at)
            VALUES (:id, :name, :slug, :plan, :is_active, :created_at)
            """
        ),
        {
            "id": str(DEFAULT_TENANT_ID),
            "name": DEFAULT_TENANT_NAME,
            "slug": DEFAULT_TENANT_SLUG,
            "plan": "free",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        },
    )
    return DEFAULT_TENANT_ID


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ------------------------------------------------------------------------
    # 1) tenants
    # ------------------------------------------------------------------------
    # Use raw ``CREATE TABLE IF NOT EXISTS`` so the migration is
    # idempotent on databases that have already been initialised by
    # ``Base.metadata.create_all`` (the conftest, for example).
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(64) NOT NULL,
                plan VARCHAR(32) NOT NULL DEFAULT 'free',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    # Alembic's ``op.create_index`` is fine; it issues ``IF NOT EXISTS``
    # only in newer versions. Use a guarded DDL for portability.
    bind.execute(
        sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_tenants_slug ON tenants (slug)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_tenants_slug ON tenants (slug)")
    )

    # Default tenant so legacy alert_log rows can be backfilled.
    default_tenant_id = _create_default_tenant(bind)

    # ------------------------------------------------------------------------
    # 2) users
    # ------------------------------------------------------------------------
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                hashed_password VARCHAR(255) NOT NULL,
                full_name VARCHAR(255),
                org_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                role VARCHAR(16) NOT NULL DEFAULT 'member',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    bind.execute(
        sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_users_org_id ON users (org_id)")
    )

    # ------------------------------------------------------------------------
    # 3) alert_log.org_id (backfilled from the default tenant)
    # ------------------------------------------------------------------------
    if "alert_log" in existing_tables:
        existing_cols = {
            c["name"] for c in inspector.get_columns("alert_log")
        }
        if "org_id" not in existing_cols:
            op.add_column(
                "alert_log",
                sa.Column(
                    "org_id",
                    postgresql.UUID(as_uuid=True),
                    nullable=True,
                ),
            )
            op.create_foreign_key(
                "fk_alert_log_org_id_tenants",
                "alert_log",
                "tenants",
                ["org_id"],
                ["id"],
                ondelete="CASCADE",
            )

        # Backfill legacy rows with the default tenant. The column is
        # NULL for existing rows because the previous schema had no
        # concept of tenants. We update in-place so legacy data is
        # never orphaned.
        bind.execute(
            sa.text(
                "UPDATE alert_log SET org_id = :tid WHERE org_id IS NULL"
            ),
            {"tid": str(default_tenant_id)},
        )


def downgrade() -> None:
    # Drop org_id from alert_log (nullable so we don't have to worry
    # about backfill on downgrade).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "alert_log" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("alert_log")}
        if "org_id" in cols:
            # Drop FK first if present; otherwise ALTER will fail.
            fks = {
                fk["name"]
                for fk in inspector.get_foreign_keys("alert_log")
                if "org_id" in fk.get("constrained_columns", [])
            }
            for fk_name in fks:
                op.drop_constraint(fk_name, "alert_log", type_="foreignkey")
            op.drop_column("alert_log", "org_id")

    # Drop users / tenants (and their indexes / constraints). Drop the
    # unique constraint first because the backing index can't be
    # dropped while the constraint references it. Use guarded DDL.
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_users_org_id"))
    bind.execute(sa.text("DROP TABLE IF EXISTS users"))
    bind.execute(sa.text("ALTER TABLE IF EXISTS tenants DROP CONSTRAINT IF EXISTS uq_tenants_slug"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_tenants_slug"))
    bind.execute(sa.text("DROP TABLE IF EXISTS tenants"))
