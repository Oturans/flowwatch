import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import async_engine, Base
from app.routes import webhooks, api, sse, github_webhooks, traces, anomalies
from app.api import auth as auth_api
from app.middleware.tenant import TenantIsolationMiddleware

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting FlowWatch API...")

    # Create tables (for development; in production use Alembic migrations)
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables ready")

    yield

    # Cleanup
    await async_engine.dispose()
    logger.info("FlowWatch API shutdown complete")


app = FastAPI(
    title="FlowWatch API",
    description="AI Workflow Observability Monitor",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tenant isolation: decode JWT and stamp request.state with org_id/user_id
app.add_middleware(TenantIsolationMiddleware)

# Include routers
app.include_router(webhooks.router)
app.include_router(api.router)
app.include_router(sse.router)
app.include_router(github_webhooks.router)
app.include_router(auth_api.router)
app.include_router(traces.router)
app.include_router(anomalies.router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "FlowWatch API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)