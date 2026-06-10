"""
Test configuration for FlowWatch backend.

The production ``app.database`` module creates a module-level
``async_engine``. Async engines are bound to the event loop that was
running when they first connected.

pytest-asyncio's default fixture loop scope is "function" (in 0.24+),
so each test gets a fresh loop, but the engine was first used on the
first test's loop. Reusing it on later loops raises
``InterfaceError: another operation is in progress``.

Solution: We re-create the engine binding for tests. The production
``async_engine`` and ``AsyncSessionLocal`` are module-level singletons;
we dispose them between tests so a fresh connection pool is created
lazily on each test's loop.
"""

import asyncio
import os
import uuid
import pytest
import pytest_asyncio

# Ensure tests have sane default DB URL even if env not set
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://flowwatch:pw@localhost:5432/flowwatch",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql+psycopg2://flowwatch:pw@localhost:5432/flowwatch",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("REDIS_BROKER", "redis://localhost:6379/0")
os.environ.setdefault("RESEND_API_KEY", "test-key")


def _dispose_safely(coro):
    """Run an async dispose on a fresh loop, ignoring errors."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro)
    except Exception:
        pass
    finally:
        loop.close()


async def _create_schema():
    """Drop & create all tables, then create partitions for today and the next 7 days.

    The ``workflow_events`` table is RANGE-partitioned by ``received_at``,
    so inserts need a partition that covers the row's date. We create
    partitions for today + 7 days to keep the test suite happy; the
    production Celery Beat task (``cleanup_old_events``) maintains these
    on a daily schedule.
    """
    from datetime import date, timedelta
    from app.database import Base
    import app.models  # noqa: F401
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Create partitions for today and the next 7 days.
        today = date.today()
        for i in range(0, 8):
            d = today + timedelta(days=i)
            table_name = f"workflow_events_y{d.strftime('%Y%m%d')}"
            start_val = d.strftime("%Y-%m-%d 00:00:00")
            end_val = (d + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
            await conn.execute(text(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name}
                PARTITION OF workflow_events
                FOR VALUES FROM ('{start_val}') TO ('{end_val}')
                """
            ))
    await engine.dispose()


async def _drop_schema():
    """Drop all tables (called at session teardown)."""
    from app.database import Base
    import app.models  # noqa: F401
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def pytest_sessionstart(session):
    """Create schema once at the start of the test session."""
    from app.config import get_settings

    get_settings.cache_clear()
    _dispose_safely(_create_schema())


def pytest_sessionfinish(session, exitstatus):
    """Drop schema at end of session."""
    _dispose_safely(_drop_schema())


def pytest_runtest_setup(item):
    """Reset engine and settings cache before each test."""
    from app import database as db_mod
    from app.config import get_settings

    # Force settings re-read (in case a test mutated env)
    get_settings.cache_clear()

    # Dispose the production async engine so the next test's loop
    # gets a fresh connection pool.
    if getattr(db_mod, "async_engine", None) is not None:
        _dispose_safely(db_mod.async_engine.dispose())


def pytest_runtest_teardown(item, nextitem):
    """Dispose engine after each test so the next test gets a fresh pool."""
    from app import database as db_mod

    if getattr(db_mod, "async_engine", None) is not None:
        _dispose_safely(db_mod.async_engine.dispose())


@pytest_asyncio.fixture
async def seeded_source():
    """
    Insert a default test webhook source with id='test-source' and return it.
    The signing_secret is 'test-secret-1234' (>= 8 chars).
    Uses a unique id derived from the current test request so concurrent /
    repeated tests don't collide on the primary key.
    """
    import inspect
    from app.database import AsyncSessionLocal
    from app.models import WebhookSource

    # Use a per-call suffix so multiple tests in the same session don't
    # collide. (Most calls are simple enough that we use a stable id; the
    # session teardown drops & recreates the schema, so collisions between
    # successive pytest runs aren't an issue.)
    source_id = "test-source"
    signing_secret = "test-secret-1234"

    # First remove any existing row with this id (idempotent).
    async with AsyncSessionLocal() as session:
        from sqlalchemy import delete
        await session.execute(
            delete(WebhookSource).where(WebhookSource.id == source_id)
        )
        await session.commit()

    source = WebhookSource(
        id=source_id,
        name="Test Source",
        signing_secret=signing_secret,
        platform="n8n",
        alert_config={},
        is_active=True,
    )
    async with AsyncSessionLocal() as session:
        session.add(source)
        await session.commit()
    return source


@pytest_asyncio.fixture
async def client():
    """
    Shared async HTTP client (httpx ASGITransport).
    """
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Sprint 1 — tenant / user fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tenant_factory():
    """Factory that creates tenants and returns them.

    Cleans up after each test by truncating the tables; the session
    teardown already drops everything, so this is defensive.
    """
    created: list = []

    async def _make(name: str = "Test Tenant", slug: str | None = None, plan: str = "free"):
        import uuid as _uuid
        from app.database import AsyncSessionLocal
        from app.models import Tenant

        slug = slug or f"t-{_uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            t = Tenant(name=name, slug=slug, plan=plan, is_active=True)
            session.add(t)
            await session.commit()
            await session.refresh(t)
            created.append(t)
            return t

    yield _make

    # No explicit cleanup — pytest_sessionfinish drops the schema.


@pytest_asyncio.fixture
async def user_factory():
    """Factory that creates users (with hashed password) bound to a tenant."""

    async def _make(
        tenant,
        email: str | None = None,
        password: str = "supersecret123",
        role: str = "member",
        is_active: bool = True,
    ):
        import uuid as _uuid
        from app.core.auth import hash_password
        from app.database import AsyncSessionLocal
        from app.models import User

        email = email or f"u-{_uuid.uuid4().hex[:8]}@example.com"
        async with AsyncSessionLocal() as session:
            u = User(
                email=email.lower(),
                hashed_password=hash_password(password),
                org_id=tenant.id,
                role=role,
                is_active=is_active,
            )
            session.add(u)
            await session.commit()
            await session.refresh(u)
            return u

    return _make


@pytest_asyncio.fixture
async def auth_headers_factory():
    """Factory that issues valid Authorization headers for a user.

    Returns a coroutine ``await _make(user) -> {"Authorization": "Bearer ..."}``.
    The token is a freshly-signed access JWT (not a stored DB value).
    """

    async def _make(user):
        from app.core.auth import create_access_token

        token = create_access_token(user.id, user.org_id)
        return {"Authorization": f"Bearer {token}"}

    return _make
