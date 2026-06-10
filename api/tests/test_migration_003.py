"""Sprint 1 — Alembic migration tests.

We test the 003 migration (tenants + users + org_id on alert_log) by
applying it on a fresh schema, asserting the resulting table shape,
and then applying the downgrade to make sure it's reversible.

We deliberately keep the test small: it doesn't try to roll forward
through 001/002 — the production alembic upgrade path does that.
"""

from __future__ import annotations

import uuid

import pytest
from alembic.config import Config as AlembicConfig
from alembic import command
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def sync_db_url():
    """Convert the asyncpg URL used in tests into a psycopg2 URL for
    Alembic (Alembic's offline/online modes use sync drivers)."""
    import os
    url = os.environ.get(
        "DATABASE_URL_SYNC",
        "postgresql+psycopg2://flowwatch:pw@localhost:5432/flowwatch",
    )
    return url


@pytest.fixture
def alembic_cfg(sync_db_url, tmp_path):
    """A minimal Alembic config pointing at the project's
    ``alembic/`` directory and the test database.
    """
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", sync_db_url)
    return cfg


def test_tenants_users_migration_idempotent_and_reversible(alembic_cfg, sync_db_url):
    """Apply 003, verify the resulting schema, downgrade to 002.

    The conftest creates the schema with ``Base.metadata.create_all``
    and never stamps the alembic version table, so we have to do
    that ourselves before running ``upgrade``. We stamp to ``002``,
    apply ``003``, then verify; downgrade to ``002`` and re-upgrade to
    confirm the migration is reversible.
    """
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import text as _text

    eng = create_engine(sync_db_url)
    insp = inspect(eng)

    # Stamp the version table at 002 so alembic knows 001+002 are
    # "applied" (their tables already exist via create_all).
    with eng.begin() as conn:
        # Create alembic_version table if it doesn't exist; mimic
        # what ``alembic stamp`` does on a fresh DB.
        conn.execute(
            _text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "    version_num VARCHAR(32) NOT NULL"
                ")"
            )
        )
        conn.execute(_text("DELETE FROM alembic_version"))
        conn.execute(
            _text(
                "INSERT INTO alembic_version (version_num) VALUES (:v)"
            ),
            {"v": "002_alert_ack"},
        )

    # Run upgrade; must apply 003 (and only 003).
    command.upgrade(alembic_cfg, "003_tenants_users")
    insp = inspect(eng)

    # New tables exist
    assert "tenants" in insp.get_table_names()
    assert "users" in insp.get_table_names()

    # Columns
    tenant_cols = {c["name"] for c in insp.get_columns("tenants")}
    assert {"id", "name", "slug", "plan", "is_active", "created_at"} <= tenant_cols

    user_cols = {c["name"] for c in insp.get_columns("users")}
    assert {
        "id",
        "email",
        "hashed_password",
        "full_name",
        "org_id",
        "role",
        "is_active",
        "created_at",
    } <= user_cols

    # alert_log got org_id
    if "alert_log" in insp.get_table_names():
        alert_cols = {c["name"] for c in insp.get_columns("alert_log")}
        assert "org_id" in alert_cols

    # Default tenant was created with the expected slug
    with eng.begin() as conn:
        row = conn.execute(
            text("SELECT slug, name FROM tenants WHERE slug = :slug"),
            {"slug": "default"},
        ).first()
    assert row is not None
    assert row.name == "Default Tenant"

    # Backfill: any existing alert_log row should have org_id NOT NULL
    with eng.begin() as conn:
        null_count = conn.execute(
            text("SELECT count(*) FROM alert_log WHERE org_id IS NULL")
        ).scalar()
    assert null_count == 0

    # Now downgrade to 002 and assert the new bits are gone.
    command.downgrade(alembic_cfg, "002_alert_ack")
    insp = inspect(eng)
    assert "tenants" not in insp.get_table_names()
    assert "users" not in insp.get_table_names()
    if "alert_log" in insp.get_table_names():
        alert_cols = {c["name"] for c in insp.get_columns("alert_log")}
        assert "org_id" not in alert_cols

    # And upgrade again (re-creates everything). This proves the
    # downgrade is "safe to roll back from" — you can re-apply 003.
    command.upgrade(alembic_cfg, "003_tenants_users")
    insp = inspect(eng)
    assert "tenants" in insp.get_table_names()
    assert "users" in insp.get_table_names()
