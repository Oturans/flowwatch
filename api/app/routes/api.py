from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
from typing import Optional
from app.database import get_db
from app.models import WebhookSource, WorkflowEvent, AlertLog
from app.schemas import (
    WebhookSourceCreate, WebhookSourceResponse, WebhookSourceUpdate,
    EventResponse, DashboardStats, AlertLogResponse
)

router = APIRouter(prefix="/api", tags=["api"])


# ============ Sources CRUD ============

@router.get("/sources", response_model=list[WebhookSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000)
):
    """List all webhook sources."""
    result = await db.execute(
        select(WebhookSource).offset(skip).limit(limit)
    )
    return result.scalars().all()


@router.post("/sources", response_model=WebhookSourceResponse)
async def create_source(
    source: WebhookSourceCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new webhook source."""
    # Check if source_id already exists
    existing = await db.execute(
        select(WebhookSource).where(WebhookSource.id == source.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Source ID already exists")

    db_source = WebhookSource(
        id=source.id,
        name=source.name,
        signing_secret=source.signing_secret,
        platform=source.platform,
        alert_config=source.alert_config,
    )
    db.add(db_source)
    await db.commit()
    await db.refresh(db_source)
    return db_source


@router.get("/sources/{source_id}", response_model=WebhookSourceResponse)
async def get_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific webhook source."""
    result = await db.execute(
        select(WebhookSource).where(WebhookSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: str,
    update: WebhookSourceUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a webhook source."""
    result = await db.execute(
        select(WebhookSource).where(WebhookSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(source, key, value)

    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a webhook source."""
    result = await db.execute(
        select(WebhookSource).where(WebhookSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    await db.delete(source)
    await db.commit()
    return {"deleted": True}


# ============ Events ============

@router.get("/events", response_model=list[EventResponse])
async def list_events(
    source_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """List events with optional filters."""
    query = select(WorkflowEvent)

    conditions = []
    if source_id:
        conditions.append(WorkflowEvent.source_id == source_id)
    if status:
        conditions.append(WorkflowEvent.status == status)
    if start_date:
        conditions.append(WorkflowEvent.received_at >= start_date)
    if end_date:
        conditions.append(WorkflowEvent.received_at <= end_date)

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(WorkflowEvent.received_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/events/{event_id}")
async def get_event(event_id: str, db: AsyncSession = Depends(get_db)):
    """Get event detail with full payload."""
    # Reject non-UUID ids so static paths like /api/events/stream win.
    import uuid as _uuid

    try:
        _uuid.UUID(event_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Event not found")

    result = await db.execute(
        select(WorkflowEvent).where(WorkflowEvent.id == event_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


# ============ Dashboard Stats ============

@router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Get aggregate dashboard statistics."""
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())

    # Total events
    total_result = await db.execute(select(func.count(WorkflowEvent.id)))
    total_events = total_result.scalar() or 0

    # Success count
    success_result = await db.execute(
        select(func.count(WorkflowEvent.id)).where(WorkflowEvent.status == "success")
    )
    success_count = success_result.scalar() or 0

    # Error count
    error_result = await db.execute(
        select(func.count(WorkflowEvent.id)).where(WorkflowEvent.status == "error")
    )
    error_count = error_result.scalar() or 0

    # Active sources (with events in last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    active_result = await db.execute(
        select(func.count(func.distinct(WorkflowEvent.source_id)))
        .where(WorkflowEvent.received_at >= week_ago)
    )
    active_sources = active_result.scalar() or 0

    # Events today
    today_result = await db.execute(
        select(func.count(WorkflowEvent.id)).where(WorkflowEvent.received_at >= today_start)
    )
    events_today = today_result.scalar() or 0

    # Success rate
    success_rate = (success_count / total_events * 100) if total_events > 0 else 0.0

    return DashboardStats(
        total_events=total_events,
        success_count=success_count,
        error_count=error_count,
        success_rate=round(success_rate, 2),
        active_sources=active_sources,
        events_today=events_today
    )


# ============ Alerts ============

@router.get("/alerts", response_model=list[AlertLogResponse])
async def list_alerts(
    source_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """List alert history."""
    query = select(AlertLog)
    if source_id:
        query = query.where(AlertLog.source_id == source_id)
    query = query.order_by(AlertLog.triggered_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# ============ Retry ============

# Per-source auto-retry configuration (read from WebhookSource.alert_config):
#   alert_config: {
#       "max_retries": 3,            # integer, default 3
#       "retry_on_status": ["error", "timeout"]  # statuses that trigger retry
#   }
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_STATUSES = ("error", "timeout", "failed")


async def _record_retry_event(
    db: AsyncSession,
    original: WorkflowEvent,
    attempt: int,
) -> WorkflowEvent:
    """Insert a new 'retried' event that mirrors the original."""
    import uuid as _uuid

    new_event = WorkflowEvent(
        id=_uuid.uuid4(),
        source_id=original.source_id,
        workflow_id=original.workflow_id,
        run_id=original.run_id,
        event_type="retried",
        status="running",
        payload={
            **(original.payload or {}),
            "retry_of": str(original.id),
            "retry_attempt": attempt,
        },
        error_message=original.error_message,
        duration_ms=original.duration_ms,
        received_at=datetime.utcnow(),
    )
    db.add(new_event)
    await db.commit()
    await db.refresh(new_event)
    return new_event


@router.post("/events/{event_id}/retry")
async def retry_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    max_retries: int = Query(3, ge=0, le=10, description="Override source's max_retries"),
):
    """
    Manually retry a failed workflow event.

    The retry is recorded as a NEW event (with ``event_type='retried'``)
    that points back to the original. The original is left intact so
    history is preserved.

    The number of retries is bounded by either the per-request override
    (``max_retries`` query param) or the source's
    ``alert_config.max_retries`` setting.
    """
    import uuid as _uuid

    # Validate UUID; reject non-UUID ids so other routes win.
    try:
        _uuid.UUID(event_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Event not found")

    # Load original event
    result = await db.execute(
        select(WorkflowEvent).where(WorkflowEvent.id == event_id)
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Event not found")

    # Look up the source to read per-source config.
    src_result = await db.execute(
        select(WebhookSource).where(WebhookSource.id == original.source_id)
    )
    source = src_result.scalar_one_or_none()
    source_max = DEFAULT_MAX_RETRIES
    retry_statuses = list(DEFAULT_RETRY_STATUSES)
    if source and source.alert_config:
        if isinstance(source.alert_config.get("max_retries"), int):
            source_max = source.alert_config["max_retries"]
        if isinstance(source.alert_config.get("retry_on_status"), list):
            retry_statuses = source.alert_config["retry_on_status"]

    effective_max = min(max_retries, source_max)

    # Only retryable statuses can be retried.
    if original.status not in retry_statuses:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Event status '{original.status}' is not retryable; "
                f"allowed: {retry_statuses}"
            ),
        )

    # Count prior retries for this event (events whose payload contains
    # retry_of == original.id). Cast payload to JSONB so the @> containment
    # operator works on PostgreSQL.
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import cast

    prior = await db.execute(
        select(func.count(WorkflowEvent.id)).where(
            cast(WorkflowEvent.payload, JSONB).contains(
                {"retry_of": str(original.id)}
            )
        )
    )
    prior_count = prior.scalar() or 0
    next_attempt = prior_count + 1

    if next_attempt > effective_max:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Max retries ({effective_max}) exceeded for this event "
                f"({prior_count} prior attempts)"
            ),
        )

    new_event = await _record_retry_event(db, original, next_attempt)

    # Re-dispatch the processing pipeline (best-effort; broker may be down).
    from app.tasks.tasks import process_event

    retry_envelope = {
        "id": str(new_event.id),
        "source_id": new_event.source_id,
        "received_at": new_event.received_at.isoformat(),
        "workflow_id": new_event.workflow_id,
        "run_id": new_event.run_id,
        "event_type": new_event.event_type,
        "status": new_event.status,
        "payload": new_event.payload,
        "error_message": new_event.error_message,
        "duration_ms": new_event.duration_ms,
        "retry_of": str(original.id),
        "retry_attempt": next_attempt,
    }
    try:
        process_event.delay(retry_envelope)
    except Exception:
        # We still return 200 because the retry event is recorded in
        # Postgres; the consumer can re-queue later.
        pass

    return {
        "status": "retry_queued",
        "original_event_id": str(original.id),
        "retry_event_id": str(new_event.id),
        "attempt": next_attempt,
        "max_attempts": effective_max,
    }


@router.get("/sources/{source_id}/retry-config")
async def get_retry_config(source_id: str, db: AsyncSession = Depends(get_db)):
    """Return the retry configuration for a source."""
    result = await db.execute(
        select(WebhookSource).where(WebhookSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    cfg = source.alert_config or {}
    return {
        "source_id": source_id,
        "max_retries": cfg.get("max_retries", DEFAULT_MAX_RETRIES),
        "retry_on_status": cfg.get("retry_on_status", list(DEFAULT_RETRY_STATUSES)),
    }