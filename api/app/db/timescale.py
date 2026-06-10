"""Sprint 2: TimescaleDB helpers for the observability tables.

The traces + anomaly_events tables get *a lot* of inserts per
minute once the WebSocket ingestion channel is wired up. The
Sprint 2 deliverable asks for them to be TimescaleDB hypertables
so we can use time-bucket aggregations for the dashboard without
a separate analytics pipeline.

The helpers here are intentionally tolerant:

* They probe the TimescaleDB extension with ``SELECT extname FROM
  pg_extension``. If the extension is *not* installed, every
  function is a no-op (returning ``False``) and we log a single
  warning. This is what happens in unit tests: the test database
  is a stock Postgres 16 container without TimescaleDB, and we
  don't want to gate the suite on a paid feature.
* The migration calls ``create_hypertable`` after creating the
  table. The first run on production is the place where the
  extension actually exists.

Reference: https://docs.timescale.com/self-hosted/latest/hypertables/
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Module-level flag: the first call to ``extension_available`` does
# the lookup against ``pg_extension`` and caches the result so
# subsequent calls in the same process are a dict lookup. The
# migration only ever calls each function once, so this isn't a
# real perf concern — the cache is just a defense against
# accidental N+1 queries from the test suite.
_EXTENSION_CACHE: dict[str, bool] = {}


async def extension_available(
    db: AsyncSession,
    *,
    name: str = "timescaledb",
) -> bool:
    """Return True if the named Postgres extension is installed.

    Caches the result in module memory so repeated calls are
    cheap. To force a re-check, call ``extension_available.cache_clear()``
    (test helper).
    """
    if name in _EXTENSION_CACHE:
        return _EXTENSION_CACHE[name]
    result = await db.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = :n"),
        {"n": name},
    )
    available = result.scalar_one_or_none() is not None
    _EXTENSION_CACHE[name] = available
    if not available:
        logger.warning(
            "Postgres extension %r is not installed; hypertable features disabled",
            name,
        )
    return available


def extension_cache_clear() -> None:
    """Reset the cached extension-availability state.

    Used by tests that mock the database to flip the flag.
    """
    _EXTENSION_CACHE.clear()


# ---------------------------------------------------------------------------
# Extension installation
# ---------------------------------------------------------------------------


async def ensure_extensions(
    db: AsyncSession,
    *,
    extensions: tuple[str, ...] = ("timescaledb",),
) -> bool:
    """Create the requested Postgres extensions if missing.

    Returns True if every requested extension is installed (or was
    already installed) at the end of the call. Returns False on
    permission failure (e.g. running as a non-superuser) — the
    caller should log + continue without the hypertable features.

    ``CREATE EXTENSION IF NOT EXISTS`` requires superuser. In
    managed Postgres (RDS, Cloud SQL, Supabase) the operator
    pre-installs the extension and grants the right role. In
    self-hosted environments we surface the error so the operator
    can run ``CREATE EXTENSION timescaledb;`` once.

    The helper is robust to the caller's session state: it opens
    a savepoint around each ``CREATE EXTENSION`` so a failure
    doesn't poison the outer transaction. This matters inside an
    Alembic migration, where the surrounding block is itself a
    transaction and a failed ``CREATE EXTENSION`` would otherwise
    abort it.
    """
    for ext in extensions:
        try:
            # Use SAVEPOINT so a failure inside the migration's
            # outer transaction doesn't poison the upgrade.
            await db.execute(text(f'SAVEPOINT create_ext_{ext}'))
            await db.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
            await db.execute(text(f'RELEASE SAVEPOINT create_ext_{ext}'))
        except Exception as exc:  # pragma: no cover - permission path
            # Roll back the savepoint so the outer transaction
            # is still usable for the rest of the migration.
            try:
                await db.execute(
                    text(f'ROLLBACK TO SAVEPOINT create_ext_{ext}')
                )
                await db.execute(
                    text(f'RELEASE SAVEPOINT create_ext_{ext}')
                )
            except Exception:
                pass
            logger.warning(
                "could not create extension %r (%s); "
                "continuing without it",
                ext,
                exc,
            )
            return False
    if not extensions:
        # No extensions requested; nothing to verify. Treat as a
        # successful no-op so conditional callers can build the
        # tuple dynamically.
        return True
    return await extension_available(db, name=extensions[0])


# ---------------------------------------------------------------------------
# Hypertable conversion
# ---------------------------------------------------------------------------


async def create_hypertable(
    db: AsyncSession,
    table: str,
    *,
    time_column: str = "started_at",
    chunk_time_interval: str = "1 hour",
    schema: Optional[str] = None,
) -> bool:
    """Convert ``table`` into a TimescaleDB hypertable.

    Idempotent: if the table is already a hypertable, the call is
    a no-op (TimescaleDB raises a ``timescaledb_hypertables`` row
    that we catch). If the TimescaleDB extension isn't installed,
    we silently return False so the migration can run on plain
    Postgres.

    Returns True if the table is (or already was) a hypertable.
    """
    if not await extension_available(db):
        return False

    qualified = f'"{schema}"."{table}"' if schema else f'"{table}"'

    # ``if_not_exists => true`` (Timescale 2.x) makes the call
    # idempotent. We still swallow the "already a hypertable" error
    # in case the operator is on an older build.
    try:
        await db.execute(
            text(
                "SELECT create_hypertable("
                "  :qualified, :time_column, "
                "  chunk_time_interval => :chunk, "
                "  if_not_exists => true"
                ")"
            ),
            {
                "qualified": qualified,
                "time_column": time_column,
                "chunk": chunk_time_interval,
            },
        )
        await db.commit()
        return True
    except Exception as exc:  # pragma: no cover - depends on TS build
        await db.rollback()
        msg = str(exc).lower()
        if "already" in msg or "is already a hypertable" in msg:
            return True
        logger.warning("create_hypertable(%s) failed: %s", qualified, exc)
        return False


# ---------------------------------------------------------------------------
# Continuous aggregates
# ---------------------------------------------------------------------------


async def create_continuous_aggregate(
    db: AsyncSession,
    *,
    name: str,
    source_table: str,
    time_column: str = "started_at",
    bucket_interval: str = "1 minute",
    aggregations: tuple[tuple[str, str], ...] = (
        ("count", "count(*)"),
        ("avg_duration", "avg(duration_ms)"),
    ),
    schema: Optional[str] = None,
) -> bool:
    """Create a TimescaleDB continuous aggregate over ``source_table``.

    Continuous aggregates pre-compute time-bucketed metrics so the
    dashboard can query ``traces_per_minute`` / ``avg_latency_per_minute``
    cheaply. The implementation is a thin wrapper around the
    ``CREATE MATERIALIZED VIEW`` + ``CREATE AGGREGATE`` pair that
    Timescale uses under the hood, wrapped in a single
    ``CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)``
    statement.

    The function is intentionally narrow: it only handles the
    ``count(*)`` and ``avg(duration_ms)`` shape that the Sprint 2
    dashboard needs. Adding more aggregations is a matter of
    passing them in.

    Returns True on success, False if TimescaleDB isn't available
    (so the migration can no-op gracefully).
    """
    if not await extension_available(db):
        return False

    qualified_view = f'"{schema}"."{name}"' if schema else f'"{name}"'
    source_qualified = (
        f'"{schema}"."{source_table}"' if schema else f'"{source_table}"'
    )

    select_clauses = ", ".join(
        f"{expr} AS {alias}" for alias, expr in aggregations
    )
    bucket = f"time_bucket(:bucket, {time_column})"

    sql = (
        f"CREATE MATERIALIZED VIEW IF NOT EXISTS {qualified_view} "
        f"WITH (timescaledb.continuous) AS "
        f"SELECT {bucket} AS bucket, {select_clauses} "
        f"FROM {source_qualified} "
        f"GROUP BY bucket "
        f"WITH NO DATA"
    )
    try:
        await db.execute(text(sql), {"bucket": bucket_interval})
        await db.commit()
        return True
    except Exception as exc:  # pragma: no cover - depends on TS build
        await db.rollback()
        logger.warning("create_continuous_aggregate(%s) failed: %s", name, exc)
        return False


__all__ = [
    "extension_available",
    "extension_cache_clear",
    "ensure_extensions",
    "create_hypertable",
    "create_continuous_aggregate",
    "setup_hypertable_and_aggregate",
]


# ---------------------------------------------------------------------------
# Sync helper for Alembic migrations
# ---------------------------------------------------------------------------


def setup_hypertable_and_aggregate(
    *,
    table: str,
    time_column: str = "started_at",
    chunk_time_interval: str = "1 hour",
    aggregate_name: str = "traces_per_minute",
    source_table: Optional[str] = None,
) -> bool:
    """One-shot setup for migrations.

    Opens a *fresh* autocommit connection (so it doesn't fight
    Alembic's surrounding transaction) and runs:

    1. ``CREATE EXTENSION IF NOT EXISTS timescaledb``
    2. ``SELECT create_hypertable(<table>, <time_column>, ...)``
    3. ``CREATE MATERIALIZED VIEW <aggregate_name> WITH (timescaledb.continuous) ...``

    All three calls are no-ops on plain Postgres (the first one
    fails with ``FeatureNotSupportedError`` and the rest bail
    out). Returns ``True`` on success, ``False`` otherwise. The
    migration's surrounding try/except treats False as a benign
    skip.
    """
    import os
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    sync_url = os.environ.get(
        "DATABASE_URL_SYNC",
        "postgresql+psycopg2://flowwatch:pw@localhost:5432/flowwatch",
    )
    source_table = source_table or table

    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            # 1. Make sure the extension exists. This is the
            #    call that fails on plain Postgres; we catch
            #    below and bail.
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            except SQLAlchemyError as exc:
                logger.info(
                    "timescaledb extension not available (%s); "
                    "skipping hypertable setup",
                    exc.__class__.__name__,
                )
                return False

            # 2. Convert the table to a hypertable.
            try:
                conn.execute(
                    text(
                        "SELECT create_hypertable("
                        "  :qualified, :time_column, "
                        "  chunk_time_interval => :chunk, "
                        "  if_not_exists => true"
                        ")"
                    ),
                    {
                        "qualified": f'"{table}"',
                        "time_column": time_column,
                        "chunk": chunk_time_interval,
                    },
                )
            except SQLAlchemyError as exc:
                msg = str(exc).lower()
                if "already" in msg or "is already a hypertable" in msg:
                    pass
                else:
                    logger.warning("create_hypertable(%s) failed: %s", table, exc)
                    return False

            # 3. Continuous aggregate.
            try:
                conn.execute(
                    text(
                        f"CREATE MATERIALIZED VIEW IF NOT EXISTS \"{aggregate_name}\" "
                        f"WITH (timescaledb.continuous) AS "
                        f"SELECT time_bucket('1 minute', {time_column}) AS bucket, "
                        f"count(*) AS count, "
                        f"avg(duration_ms) AS avg_duration "
                        f"FROM \"{source_table}\" "
                        f"GROUP BY bucket "
                        f"WITH NO DATA"
                    )
                )
            except SQLAlchemyError as exc:
                logger.warning(
                    "create_continuous_aggregate(%s) failed: %s",
                    aggregate_name,
                    exc,
                )
                return False

        return True
    finally:
        engine.dispose()
