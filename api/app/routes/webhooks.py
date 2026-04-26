import json
import hmac
import hashlib
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Response
from svix.webhooks import Webhook as SvixWebhook
import redis.asyncio as redis
from app.config import get_settings
from app.schemas import EventCreate

settings = get_settings()
router = APIRouter(prefix="/api/webhook", tags=["webhook"])

# Redis clients for different purposes
redis_client = redis.from_url(settings.redis_url, decode_responses=True)
redis_rate_limit = redis.from_url(settings.redis_url.replace("/0", f"/{settings.redis_rate_limit_db}"), decode_responses=True)
redis_pubsub = redis.from_url(settings.redis_url.replace("/0", f"/{settings.redis_pubsub_db}"), decode_responses=True)

REPLAY_TTL = 300  # 5 minutes for replay protection


def verify_svix_signature(body: bytes, headers: dict, secret: str) -> bool:
    """Verify Svix webhook signature."""
    try:
        msg_id = headers.get("svix-id")
        timestamp = headers.get("svix-timestamp")
        signature = headers.get("svix-signature")

        if not all([msg_id, timestamp, signature]):
            return False

        wh = SvixWebhook(secret)
        wh.verify(body, {
            "svix-id": msg_id,
            "svix-timestamp": timestamp,
            "svix-signature": signature,
        })
        return True
    except Exception:
        return False


def verify_hmac_sha256(body: bytes, signature: str, secret: str) -> bool:
    """Verify raw HMAC-SHA256 signature (fallback for n8n/Make)."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Support both "sha256=<signature>" and raw signature formats
    if signature.startswith("sha256="):
        expected_sig = f"sha256={expected}"
    else:
        expected_sig = expected
    return hmac.compare_digest(expected_sig, signature)


async def check_rate_limit(source_id: str) -> bool:
    """Rate limit per source_id using Redis token bucket."""
    key = f"rate_limit:webhook:{source_id}"
    current = await redis_rate_limit.get(key)
    if current is None:
        await redis_rate_limit.setex(key, 60, 1)
        return True

    if int(current) >= settings.rate_limit_per_minute:
        return False

    await redis_rate_limit.incr(key)
    return True


async def check_replay(message_id: str) -> bool:
    """Check if message_id has been seen (replay protection)."""
    key = f"replay:{message_id}"
    exists = await redis_client.get(key)
    if exists:
        return True  # Replay detected

    await redis_client.setex(key, REPLAY_TTL, "1")
    return False


async def store_event_locally(event_data: dict, source_id: str) -> dict:
    """Store event in Redis for async processing (pub/sub for SSE)."""
    event_id = str(uuid.uuid4())
    event = {
        "id": event_id,
        "source_id": source_id,
        "received_at": datetime.utcnow().isoformat(),
        **event_data
    }
    # Store in Redis list for processing
    await redis_client.lpush(f"events:pending:{source_id}", json.dumps(event))
    # Publish for SSE subscribers
    await redis_pubsub.publish("flowwatch:events", json.dumps(event))
    return event


@router.post("/{source_id}")
async def ingest_webhook(
    source_id: str,
    request: Request,
    response: Response
):
    """
    Ingest webhook events from n8n, Make, or other platforms.
    Always returns 200 for valid events (per research gotcha #7).
    """
    # 1. Read raw body BEFORE anything else (research gotcha #2)
    body = await request.body()

    # 2. Get source config (we'll verify this in the processing step)
    # For now, extract signature headers
    headers = dict(request.headers)

    # 3. Check rate limit
    if not await check_rate_limit(source_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # 4. Extract message_id for replay protection (Svix headers)
    message_id = headers.get("svix-id") or headers.get("x-message-id") or str(uuid.uuid4())

    # 5. Check replay protection
    if await check_replay(message_id):
        # Silently accept duplicate - don't reprocess
        return {"status": "accepted", "duplicate": True}

    # 6. Parse event data
    try:
        event_data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 7. Basic validation
    if not event_data.get("workflow_id"):
        raise HTTPException(status_code=400, detail="Missing workflow_id")

    # 8. Store event for async processing
    event = await store_event_locally(event_data, source_id)

    # 9. Return 200 for valid events (gotcha #7)
    return {"status": "accepted", "event_id": event["id"]}


@router.post("/{source_id}/verify")
async def verify_webhook_signature(
    source_id: str,
    request: Request
):
    """Verify webhook signature for a given source."""
    body = await request.body()
    headers = dict(request.headers)

    # Get signature (Svix or raw HMAC)
    signature = headers.get("svix-signature") or headers.get("x-hmac-signature") or ""

    # For verification endpoint, just check format
    return {
        "valid": bool(signature),
        "source_id": source_id
    }