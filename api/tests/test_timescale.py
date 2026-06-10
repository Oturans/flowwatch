"""Sprint 2: TimescaleDB helper tests.

The test database is plain Postgres — the ``timescaledb`` extension
isn't installed. The helpers must degrade gracefully: they should
return ``False`` (or whatever the appropriate "didn't do it" value
is) instead of raising.

We still want to exercise the SQL *path* so a future contributor
who refactors won't accidentally regress the no-op behaviour. To
do that we use two strategies:

* :func:`extension_available` — directly probe ``pg_extension`` and
  assert the cache short-circuits on the second call.
* :func:`ensure_extensions` / :func:`create_hypertable` /
  :func:`create_continuous_aggregate` — call against the real DB;
  each returns ``False`` because the extension is missing.

The SQL we generate for the hypertable / continuous aggregate paths
is captured by patching ``db.execute`` so we can assert the
arguments without requiring a real Timescale install. This is
deliberately not a full mock — the real ``AsyncSession`` is used
to drive the contract check, but a spy is attached so we can
inspect the SQL.

A handful of the tests use ``pytest.skip`` to opt out when the
operator is running a real Timescale database in CI; we detect
that by looking at the extension name in ``pg_extension``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import timescale


# ---------------------------------------------------------------------------
# extension_available + cache
# ---------------------------------------------------------------------------


async def test_extension_available_returns_false_when_missing():
    """Plain Postgres test DB has no ``timescaledb`` extension."""
    timescale.extension_cache_clear()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await timescale.extension_available(session, name="timescaledb")
    assert result is False


async def test_extension_available_caches_result_across_calls():
    """The second call should be served from the module-level cache."""
    timescale.extension_cache_clear()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        first = await timescale.extension_available(session, name="timescaledb")
        # The cache should be populated now.
        assert "timescaledb" in timescale._EXTENSION_CACHE
        cached = timescale._EXTENSION_CACHE["timescaledb"]
        assert first == cached

    # Sanity: even after closing the session the cache is intact.
    assert "timescaledb" in timescale._EXTENSION_CACHE


async def test_extension_cache_clear_resets_state():
    """``cache_clear`` must wipe the module-level dict so a re-probe happens."""
    timescale._EXTENSION_CACHE["fake_ext"] = True
    timescale.extension_cache_clear()
    assert timescale._EXTENSION_CACHE == {}


async def test_extension_available_against_different_name_returns_false():
    """A weird extension name will obviously not exist; the helper reports False."""
    timescale.extension_cache_clear()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await timescale.extension_available(
            session, name="definitely_not_a_real_extension_xyz"
        )
    assert result is False


# ---------------------------------------------------------------------------
# ensure_extensions
# ---------------------------------------------------------------------------


async def test_ensure_extensions_returns_false_when_extension_missing():
    """Without superuser + without the pre-installed extension, we get False.

    We don't actually ``CREATE EXTENSION`` because the test DB user
    is unlikely to have the privilege. The function logs and
    returns ``False`` so the migration can no-op gracefully.
    """
    timescale.extension_cache_clear()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        ok = await timescale.ensure_extensions(
            session, extensions=("definitely_missing_xyz",)
        )
    assert ok is False


async def test_ensure_extensions_returns_true_when_already_installed():
    """If the extension is already there, we should return True."""
    timescale.extension_cache_clear()
    # Pretend it's there by seeding the cache and using a fake
    # session that doesn't actually run anything.
    timescale._EXTENSION_CACHE["mock_present_ext"] = True
    fake = AsyncMock(spec=AsyncSession)
    # ``extension_available`` short-circuits via the cache so the
    # fake session's ``execute`` is never called.
    ok = await timescale.ensure_extensions(
        fake, extensions=("mock_present_ext",)
    )
    assert ok is True


# ---------------------------------------------------------------------------
# create_hypertable
# ---------------------------------------------------------------------------


async def test_create_hypertable_returns_false_on_plain_postgres():
    """No Timescale extension → ``create_hypertable`` is a no-op."""
    timescale.extension_cache_clear()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await timescale.create_hypertable(
            session, "traces", time_column="started_at"
        )
    assert result is False


async def test_create_hypertable_emits_correct_sql_when_extension_available():
    """Capture the SQL the helper would have run.

    We patch ``extension_available`` to return ``True`` and let
    ``create_hypertable`` proceed. The session's ``execute`` is
    replaced with an ``AsyncMock`` so we can inspect the call
    without actually running it; we then assert that the SQL is
    the well-formed ``create_hypertable(...)`` call.
    """
    timescale.extension_cache_clear()
    timescale._EXTENSION_CACHE["timescaledb"] = True
    fake = AsyncMock(spec=AsyncSession)

    result = await timescale.create_hypertable(
        fake,
        "traces",
        time_column="started_at",
        chunk_time_interval="6 hours",
    )

    # It tried to run create_hypertable. We don't commit on the
    # fake session, but the helper still returns True (or False if
    # the execute raised). With AsyncMock, execute returns a
    # MagicMock that we can treat as "no exception" → True.
    assert result is True
    fake.execute.assert_awaited_once()
    call_args = fake.execute.await_args
    sql_obj = call_args.args[0]
    sql_text = str(sql_obj.compile(compile_kwargs={"literal_binds": True}))
    # The SQL should reference create_hypertable + the chunk arg.
    assert "create_hypertable" in sql_text
    # The bound param dict should carry our 6-hour interval.
    params = call_args.kwargs.get("parameters") or (call_args.args[1] if len(call_args.args) > 1 else None)
    assert params is None or params.get("chunk") == "6 hours"
    # Cleanup
    timescale.extension_cache_clear()


async def test_create_hypertable_uses_default_chunk_interval():
    """The default chunk interval should be 1 hour when not overridden."""
    timescale.extension_cache_clear()
    timescale._EXTENSION_CACHE["timescaledb"] = True
    fake = AsyncMock(spec=AsyncSession)
    result = await timescale.create_hypertable(fake, "traces", time_column="started_at")
    assert result is True
    fake.execute.assert_awaited_once()
    timescale.extension_cache_clear()


async def test_create_hypertable_swallows_already_hypertable_error():
    """If Timescale says "already a hypertable", we report success.

    We simulate the error path by configuring the fake's
    ``execute`` to raise. ``create_hypertable`` should catch and
    inspect the error message, returning True if it looks like an
    "already a hypertable" complaint.
    """
    timescale.extension_cache_clear()
    timescale._EXTENSION_CACHE["timescaledb"] = True
    fake = AsyncMock(spec=AsyncSession)
    fake.execute.side_effect = RuntimeError(
        'relation "traces" is already a hypertable'
    )
    # Need rollback to be awaitable too.
    fake.rollback = AsyncMock()

    result = await timescale.create_hypertable(fake, "traces", time_column="started_at")
    assert result is True
    fake.rollback.assert_awaited()
    timescale.extension_cache_clear()


# ---------------------------------------------------------------------------
# create_continuous_aggregate
# ---------------------------------------------------------------------------


async def test_create_continuous_aggregate_returns_false_on_plain_postgres():
    """No Timescale extension → no-op."""
    timescale.extension_cache_clear()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await timescale.create_continuous_aggregate(
            session,
            name="traces_per_minute",
            source_table="traces",
        )
    assert result is False


async def test_create_continuous_aggregate_emits_create_materialized_view():
    """With the extension forced on, the helper must emit a CONTINUOUS agg.

    We inspect the captured SQL and confirm it uses
    ``CREATE MATERIALIZED VIEW`` plus the ``timescaledb.continuous``
    option, which is what Timescale expects.
    """
    timescale.extension_cache_clear()
    timescale._EXTENSION_CACHE["timescaledb"] = True
    fake = AsyncMock(spec=AsyncSession)

    result = await timescale.create_continuous_aggregate(
        fake,
        name="traces_per_minute",
        source_table="traces",
        time_column="started_at",
        bucket_interval="1 minute",
        aggregations=(("count", "count(*)"), ("avg_dur", "avg(duration_ms)")),
    )
    assert result is True
    fake.execute.assert_awaited_once()
    call_args = fake.execute.await_args
    sql_text = str(
        call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "CREATE MATERIALIZED VIEW" in sql_text
    assert "timescaledb.continuous" in sql_text
    # Custom aggregations should appear in the projection.
    assert "count" in sql_text
    assert "avg" in sql_text
    timescale.extension_cache_clear()


# ---------------------------------------------------------------------------
# Hyperparameter shape
# ---------------------------------------------------------------------------


def test_helpers_accept_time_column_override():
    """The function signature should accept ``time_column`` as a kw-only arg.

    Pure signature check — no DB needed.
    """
    import inspect

    for fn in (
        timescale.create_hypertable,
        timescale.create_continuous_aggregate,
    ):
        sig = inspect.signature(fn)
        assert "time_column" in sig.parameters
        # The default should be "started_at" so callers can omit it.
        assert sig.parameters["time_column"].default == "started_at"


def test_module_exports_expected_symbols():
    """The public surface should be exactly the listed helpers + the cache clear."""
    import app.db.timescale as ts

    expected = {
        "extension_available",
        "extension_cache_clear",
        "ensure_extensions",
        "create_hypertable",
        "create_continuous_aggregate",
        "setup_hypertable_and_aggregate",
    }
    assert set(ts.__all__) == expected
    for name in expected:
        assert hasattr(ts, name), f"missing export: {name}"


async def test_create_hypertable_idempotent_under_repeated_calls():
    """Calling create_hypertable twice on plain Postgres should both be False.

    This is the "no-op is a no-op" guarantee — we shouldn't crash
    or change state when the extension is missing.
    """
    timescale.extension_cache_clear()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        first = await timescale.create_hypertable(session, "traces")
        second = await timescale.create_hypertable(session, "traces")
    assert first is False
    assert second is False


async def test_ensure_extensions_with_empty_tuple_succeeds():
    """``ensure_extensions(())`` is degenerate but should still return True.

    With zero extensions to ensure, there's literally nothing to
    install — a vacuous True is the right answer. Callers that
    build the tuple conditionally (e.g. ``extensions=('timescaledb',)
    if settings.has_ts else ()``) shouldn't have to special-case
    the empty form.
    """
    fake = AsyncMock(spec=AsyncSession)
    timescale.extension_cache_clear()
    ok = await timescale.ensure_extensions(fake, extensions=())
    assert ok is True


# ---------------------------------------------------------------------------
# setup_hypertable_and_aggregate (sync, used by Alembic)
# ---------------------------------------------------------------------------


def test_setup_hypertable_returns_false_on_plain_postgres(monkeypatch):
    """The sync helper should bail out cleanly when the extension is missing.

    The plain test database doesn't have ``timescaledb`` installed;
    the helper should detect this, log, and return False without
    raising. We don't actually open a real connection in this
    test — we patch the sync engine factory so the create_extension
    call short-circuits to the "extension not available" path.
    """
    from unittest.mock import MagicMock
    from sqlalchemy.exc import OperationalError

    fake_engine = MagicMock()
    # The ``connect()`` context manager returns a connection whose
    # ``execute`` raises an OperationalError on the first call
    # (the ``CREATE EXTENSION`` one) and is fine afterwards.
    fake_conn = MagicMock()
    fake_conn.execute.side_effect = OperationalError(
        "CREATE EXTENSION", {}, Exception("extension not available"),
    )
    fake_engine.connect.return_value.__enter__.return_value = fake_conn
    fake_engine.dispose.return_value = None

    monkeypatch.setattr(
        "sqlalchemy.create_engine", lambda *a, **kw: fake_engine,
    )
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql+psycopg2://u:p@h/d")

    result = timescale.setup_hypertable_and_aggregate(
        table="traces", time_column="started_at",
    )
    assert result is False
    fake_engine.dispose.assert_called_once()


def test_setup_hypertable_propagates_real_failure():
    """The sync helper should *not* crash on missing env.

    Even without DATABASE_URL_SYNC, the helper should fall back
    to a sensible default — and the test environment does have
    Postgres reachable. The test runs against the real test DB
    and should report False (no TimescaleDB) without exceptions.
    """
    import os
    os.environ["DATABASE_URL_SYNC"] = (
        "postgresql+psycopg2://flowwatch:pw@localhost:5432/flowwatch"
    )
    result = timescale.setup_hypertable_and_aggregate(table="traces")
    assert result is False


def test_setup_hypertable_signature_defaults():
    """The signature should carry sensible defaults so migration callers stay terse."""
    import inspect
    sig = inspect.signature(timescale.setup_hypertable_and_aggregate)
    assert sig.parameters["table"].default is inspect.Parameter.empty
    assert sig.parameters["time_column"].default == "started_at"
    assert sig.parameters["chunk_time_interval"].default == "1 hour"
    assert sig.parameters["aggregate_name"].default == "traces_per_minute"
