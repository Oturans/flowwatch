from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import create_engine, text
from contextlib import asynccontextmanager
import uuid
from app.config import get_settings

settings = get_settings()

# Async engine for FastAPI
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,
)

# Sync engine for Celery tasks
sync_engine = create_engine(
    settings.database_url_sync,
    echo=settings.debug,
    pool_size=10,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Tenant context (Sprint 1)
# ---------------------------------------------------------------------------
#
# Row-level security policies in PostgreSQL use the GUC
# ``app.org_id`` to scope queries to the active tenant. We expose
# a couple of helpers so routes and the tenant middleware can stamp
# the GUC at the right point in the request lifecycle.


async def set_tenant_context(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Stamp the per-request ``app.org_id`` GUC for the open session.

    Idempotent: calling twice with the same value is a no-op (apart
    from the network round-trip).
    """
    await db.execute(
        text("SELECT set_config('app.org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )


def clear_tenant_context_sync() -> None:
    """Reset the ``app.org_id`` GUC for sync engine consumers (Celery).

    Use after a task has finished using tenant context. Safe to call
    outside a transaction.
    """
    with sync_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.org_id', '', false)"))