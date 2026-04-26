from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as redis
from app.config import get_settings
import asyncio

settings = get_settings()
router = APIRouter(prefix="/api", tags=["sse"])

redis_pubsub_url = settings.redis_url.replace("/0", f"/{settings.redis_pubsub_db}")


@router.get("/events/stream")
async def event_stream(request: Request):
    """
    Server-Sent Events endpoint for real-time event updates.
    Uses Redis pub/sub to broadcast events to all connected clients.
    """
    pubsub = redis.from_url(redis_pubsub_url, decode_responses=True)
    await pubsub.subscribe("flowwatch:events")

    async def generate():
        try:
            channel = pubsub.pubsub()
            # Send initial connection message
            yield "data: {\"type\": \"connected\"}\n\n"

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                message = await channel.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    yield f"data: {message['data']}\n\n"

                await asyncio.sleep(0.1)

        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "flowwatch-api"}