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