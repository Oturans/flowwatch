"""Sprint 2: WebSocket trace ingestion + REST listing.

Endpoints:

* ``WS  /ws/orgs/{org_id}/traces?token=<jwt>`` — accepts JSON
  ``TraceIngest`` payloads and persists them. The client gets a
  structured ACK (``{"type": "ack", "id": "..."}``) per message.

* ``GET  /api/orgs/{org_id}/traces`` — paginated list of stored
  traces, newest first. Supports ``workflow_id``, ``status``,
  ``limit`` and ``since`` (ISO timestamp) filters.

* ``GET  /api/orgs/{org_id}/traces/stream`` — Server-Sent Events
  stream that fans out new traces to dashboard clients via Redis
  pub/sub. (Same shape as the existing event stream so the
  dashboard can adopt it with minimal change.)

Auth model:

* The WebSocket authenticates via the ``token`` query parameter
  (browsers can't send custom headers on ``new WebSocket``). The
  REST endpoints expect a normal ``Authorization: Bearer`` header
  and reuse the Sprint 1 ``get_current_user`` / ``require_org_access``
  machinery.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as redis
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import (
    ACCESS,
    decode_token,
    get_current_user,
)
from app.database import AsyncSessionLocal, get_db
from app.models import Trace, User
from app.schemas.observability import TraceIngest, TraceResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["traces"])

settings = get_settings()
redis_pubsub_url = settings.redis_url.replace("/0", f"/{settings.redis_pubsub_db}")


# ---------------------------------------------------------------------------
# Pub/Sub channel
# ---------------------------------------------------------------------------

# Dedicated channel for trace events. Existing ``flowwatch:events``
# is for the legacy webhook pipeline; the trace stream is a separate
# concern so subscribers can opt in.
TRACE_PUBSUB_CHANNEL = "flowwatch:traces"


# Per-process WebSocket connection registry. We keep this in-memory
# so a single FastAPI worker can fan out the trace to clients that
# *prefer* an in-process connection (low-latency, no Redis hop).
# For horizontal scaling we also publish to Redis and have the SSE
# stream pick it up.
class _ConnectionRegistry:
    """Tracks active WebSocket connections per org."""

    def __init__(self) -> None:
        self._by_org: dict[uuid.UUID, set[WebSocket]] = {}

    def add(self, org_id: uuid.UUID, ws: WebSocket) -> None:
        self._by_org.setdefault(org_id, set()).add(ws)

    def discard(self, org_id: uuid.UUID, ws: WebSocket) -> None:
        if org_id in self._by_org:
            self._by_org[org_id].discard(ws)
            if not self._by_org[org_id]:
                self._by_org.pop(org_id, None)

    async def broadcast(self, org_id: uuid.UUID, payload: dict) -> int:
        """Send ``payload`` to every WS in the org. Returns delivery count."""
        conns = list(self._by_org.get(org_id, ()))
        if not conns:
            return 0
        data = json.dumps(payload, default=str)
        delivered = 0
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(data)
                delivered += 1
            except Exception:
                # The socket is dead; we'll drop it below.
                dead.append(ws)
        for ws in dead:
            self.discard(org_id, ws)
        return delivered


connection_registry = _ConnectionRegistry()


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


async def _authenticate_ws(websocket: WebSocket, org_id: uuid.UUID) -> Optional[User]:
    """Resolve the bearer token from ``?token=`` and return the user.

    Returns ``None`` if authentication fails (and closes the socket
    with an appropriate code so the client can react).
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="missing token")
        return None
    try:
        data = decode_token(token, expected_type=ACCESS)
    except HTTPException as exc:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=f"auth failed: {exc.detail}",
        )
        return None

    if data.org_id != org_id:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="token does not match org_id",
        )
        return None

    # Look the user up. We don't need to lazy-load the tenant here;
    # the org check is the only thing that matters for trace auth.
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == data.user_id))
        user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="user not found or inactive",
        )
        return None
    return user


async def _persist_trace(org_id: uuid.UUID, payload: TraceIngest) -> Trace:
    """Insert a trace row; return the persisted model."""
    async with AsyncSessionLocal() as session:
        trace = Trace(
            org_id=org_id,
            trace_id=payload.trace_id,
            workflow_id=payload.workflow_id,
            name=payload.name,
            source=payload.source,
            status=payload.status,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            duration_ms=payload.duration_ms,
            attributes=payload.attributes,
            error_message=payload.error_message,
            spans=payload.spans or [],
        )
        session.add(trace)
        await session.commit()
        await session.refresh(trace)
        return trace


async def _publish_trace(trace: Trace) -> int:
    """Publish a trace to in-process clients and Redis subscribers."""
    payload = {
        "type": "trace",
        "id": str(trace.id),
        "org_id": str(trace.org_id),
        "trace_id": trace.trace_id,
        "name": trace.name,
        "status": trace.status,
        "started_at": trace.started_at.isoformat(),
        "ended_at": trace.ended_at.isoformat() if trace.ended_at else None,
        "duration_ms": trace.duration_ms,
        "workflow_id": trace.workflow_id,
        "source": trace.source,
        "attributes": trace.attributes,
        "error_message": trace.error_message,
        "spans": getattr(trace, "spans", None) or [],
    }
    # In-process broadcast
    delivered = await connection_registry.broadcast(trace.org_id, payload)
    # Redis pub/sub (used by SSE stream + future workers)
    try:
        client = redis.from_url(redis_pubsub_url, decode_responses=True)
        await client.publish(TRACE_PUBSUB_CHANNEL, json.dumps(payload, default=str))
        await client.close()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("failed to publish trace to redis: %s", exc)
    return delivered


@router.websocket("/ws/orgs/{org_id}/traces")
async def traces_ws(websocket: WebSocket, org_id: uuid.UUID):
    """Authenticated WebSocket endpoint for trace ingestion.

    Protocol:

    * Client connects with ``?token=<jwt>``. The org id in the URL
      MUST match the token's ``org_id`` claim.
    * Client sends one JSON object per message in the shape of
      ``TraceIngest``. Server replies with::

          {"type": "ack", "id": "<trace uuid>"}

      on success, or::

          {"type": "error", "message": "..."}

      on failure (validation error, persistence error, etc).
    * Client may send ``{"type": "ping"}`` at any time; the server
      replies with ``{"type": "pong"}``. Useful for keep-alive.
    * Server may push ``{"type": "trace", ...}`` messages to the
      client (in-process broadcast) so a single WebSocket can also
      *read* its own org's traces.
    """
    await websocket.accept()
    user = await _authenticate_ws(websocket, org_id)
    if user is None:
        return

    connection_registry.add(org_id, websocket)
    logger.info("ws connected org=%s user=%s", org_id, user.id)

    try:
        await websocket.send_json({"type": "ready", "org_id": str(org_id)})
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                await websocket.send_json(
                    {"type": "error", "message": f"invalid JSON: {exc}"}
                )
                continue

            if not isinstance(data, dict):
                await websocket.send_json(
                    {"type": "error", "message": "message must be a JSON object"}
                )
                continue

            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            try:
                payload = TraceIngest.model_validate(data)
            except Exception as exc:  # pydantic.ValidationError or anything else
                await websocket.send_json(
                    {"type": "error", "message": f"validation: {exc}"}
                )
                continue

            try:
                trace = await _persist_trace(org_id, payload)
            except Exception as exc:  # pragma: no cover - DB error path
                logger.exception("failed to persist trace")
                await websocket.send_json(
                    {"type": "error", "message": f"persistence: {exc}"}
                )
                continue

            await _publish_trace(trace)
            await websocket.send_json({"type": "ack", "id": str(trace.id)})

    except WebSocketDisconnect:
        logger.info("ws disconnected org=%s", org_id)
    finally:
        connection_registry.discard(org_id, websocket)


# ---------------------------------------------------------------------------
# Auth dependency for trace endpoints
# ---------------------------------------------------------------------------


async def require_org_member(
    org_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> User:
    """Return the authenticated user if they belong to ``org_id``.

    We can't use ``require_org_access(org_id)`` here because the
    factory takes the org id at *definition* time; FastAPI doesn't
    have access to the path parameter at that point. This dependency
    inlines the check.
    """
    if user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: user does not belong to this organization",
        )
    return user


# ---------------------------------------------------------------------------
# REST listing
# ---------------------------------------------------------------------------


@router.get("/api/orgs/{org_id}/traces", response_model=list[TraceResponse])
async def list_traces(
    org_id: uuid.UUID,
    workflow_id: Optional[str] = Query(None, max_length=128),
    status_filter: Optional[str] = Query(None, alias="status", max_length=16),
    limit: int = Query(50, ge=1, le=500),
    since: Optional[datetime] = Query(None, description="ISO timestamp"),
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    """List recent traces for the org, newest first.

    Filters:

    * ``workflow_id`` — exact match
    * ``status``      — exact match (``ok``/``error``/``running``/...)
    * ``since``       — only return traces whose ``started_at`` is
      greater than or equal to the supplied ISO timestamp.

    Pagination is intentionally simple: ``limit`` controls the
    page size and the result is ordered ``started_at DESC``.
    """
    stmt = select(Trace).where(Trace.org_id == org_id)
    if workflow_id is not None:
        stmt = stmt.where(Trace.workflow_id == workflow_id)
    if status_filter is not None:
        stmt = stmt.where(Trace.status == status_filter)
    if since is not None:
        stmt = stmt.where(Trace.started_at >= since)
    stmt = stmt.order_by(Trace.started_at.desc()).limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# SSE stream (read-only fan-out)
# ---------------------------------------------------------------------------
#
# NOTE: this route is registered BEFORE the detail route below.
# FastAPI matches routes in declaration order; if the detail
# route (``/api/orgs/{org_id}/traces/{trace_db_id}``) is checked
# first, a request to ``/traces/stream`` will fail with 422 because
# the literal string "stream" is not a valid UUID. Keeping the
# static path first avoids the ambiguity without changing the
# public contract.


@router.get("/api/orgs/{org_id}/traces/stream")
async def stream_traces(
    org_id: uuid.UUID,
    user: User = Depends(require_org_member),
):
    """SSE stream of new traces for the org. Same auth as the REST list."""
    from fastapi.responses import StreamingResponse

    client = redis.from_url(redis_pubsub_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(TRACE_PUBSUB_CHANNEL)

    async def generate():
        try:
            yield "data: {\"type\": \"connected\"}\n\n"
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    try:
                        payload = json.loads(msg["data"])
                        if payload.get("org_id") == str(org_id):
                            yield f"data: {json.dumps(payload, default=str)}\n\n"
                    except (json.JSONDecodeError, TypeError):
                        continue
                await asyncio.sleep(0.05)
        finally:
            try:
                await pubsub.unsubscribe()
            except Exception:
                pass
            try:
                await pubsub.close()
            except Exception:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Trace detail (registered AFTER the stream route above)
# ---------------------------------------------------------------------------


@router.get(
    "/api/orgs/{org_id}/traces/{trace_db_id}",
    response_model=TraceResponse,
)
async def get_trace(
    org_id: uuid.UUID,
    trace_db_id: uuid.UUID,
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    """Return a single trace by primary key, including its DAG spans.

    The ``trace_db_id`` is the internal ``traces.id`` UUID returned
    by the list / stream endpoints. We look it up scoped to the
    caller's org so a leaked id from another tenant is harmless.
    """
    result = await db.execute(
        select(Trace).where(Trace.id == trace_db_id, Trace.org_id == org_id)
    )
    trace = result.scalar_one_or_none()
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="trace not found",
        )
    return trace


__all__ = ["router", "connection_registry", "TRACE_PUBSUB_CHANNEL"]
