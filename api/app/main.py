import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import redis.asyncio as redis

from app.config import get_settings
from app.database import async_engine, Base
from app.routes import webhooks, api, sse

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Rate limiter
limiter = Limiter(key_func=get_remote_address, storage_uri=f"redis://{settings.redis_url.replace('redis://', '').split('/')[0]}/2")
limiter._rate_limit_exceeded_handler = _rate_limit_exceeded_handler

# Redis client for rate limiting
redis_url_parts = settings.redis_url.replace("redis://", "").split("/")
redis_host = redis_url_parts[0].split(":")[0]
redis_port = redis_url_parts[0].split(":")[1] if ":" in redis_url_parts[0] else "6379"
redis_rate_limit_client = redis.from_url(f"redis://{redis_host}:{redis_port}/2", decode_responses=True)


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

# Add rate limiter
app.state.limiter = limiter

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(webhooks.router)
app.include_router(api.router)
app.include_router(sse.router)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."}
    )


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