"""Sprint 2: anomaly detection REST API.

Endpoints:

* ``GET    /api/orgs/{org_id}/anomaly-rules``         — list rules
* ``POST   /api/orgs/{org_id}/anomaly-rules``         — create rule
* ``GET    /api/orgs/{org_id}/anomaly-rules/{id}``    — retrieve
* ``PUT    /api/orgs/{org_id}/anomaly-rules/{id}``    — update rule
* ``DELETE /api/orgs/{org_id}/anomaly-rules/{id}``    — delete rule
* ``GET    /api/orgs/{org_id}/anomaly-events``        — recent events
* ``POST   /api/orgs/{org_id}/anomaly-events/{id}/ack`` — acknowledge
* ``POST   /api/orgs/{org_id}/anomaly-rules/{id}/evaluate`` — run on demand

All endpoints require the user to be a member of the org.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.anomaly_engine import evaluate_org
from app.core.auth import get_current_user
from app.database import get_db
from app.models import AnomalyEvent, AnomalyRule, User
from app.schemas.observability import (
    AnomalyEventAck,
    AnomalyEventResponse,
    AnomalyRuleCreate,
    AnomalyRuleResponse,
    AnomalyRuleUpdate,
)

router = APIRouter(tags=["anomalies"])


# ---------------------------------------------------------------------------
# Org-scoped auth dependency (same pattern as traces.py)
# ---------------------------------------------------------------------------


async def require_org_member(
    org_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> User:
    if user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: user does not belong to this organization",
        )
    return user


# ---------------------------------------------------------------------------
# Rules CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/api/orgs/{org_id}/anomaly-rules",
    response_model=list[AnomalyRuleResponse],
)
async def list_anomaly_rules(
    org_id: uuid.UUID,
    enabled: Optional[bool] = Query(None),
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AnomalyRule).where(AnomalyRule.org_id == org_id)
    if enabled is not None:
        stmt = stmt.where(AnomalyRule.enabled.is_(enabled))
    stmt = stmt.order_by(AnomalyRule.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/orgs/{org_id}/anomaly-rules",
    response_model=AnomalyRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_anomaly_rule(
    org_id: uuid.UUID,
    body: AnomalyRuleCreate,
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    rule = AnomalyRule(
        org_id=org_id,
        name=body.name,
        rule_type=body.rule_type,
        threshold=body.threshold,
        window_seconds=body.window_seconds,
        workflow_id=body.workflow_id,
        enabled=body.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get(
    "/api/orgs/{org_id}/anomaly-rules/{rule_id}",
    response_model=AnomalyRuleResponse,
)
async def get_anomaly_rule(
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnomalyRule).where(
            AnomalyRule.org_id == org_id,
            AnomalyRule.id == rule_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


@router.put(
    "/api/orgs/{org_id}/anomaly-rules/{rule_id}",
    response_model=AnomalyRuleResponse,
)
async def update_anomaly_rule(
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    body: AnomalyRuleUpdate,
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnomalyRule).where(
            AnomalyRule.org_id == org_id,
            AnomalyRule.id == rule_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")

    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field_name, value)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete(
    "/api/orgs/{org_id}/anomaly-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_anomaly_rule(
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnomalyRule).where(
            AnomalyRule.org_id == org_id,
            AnomalyRule.id == rule_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    await db.delete(rule)
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@router.get(
    "/api/orgs/{org_id}/anomaly-events",
    response_model=list[AnomalyEventResponse],
)
async def list_anomaly_events(
    org_id: uuid.UUID,
    rule_id: Optional[uuid.UUID] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AnomalyEvent).where(AnomalyEvent.org_id == org_id)
    if rule_id is not None:
        stmt = stmt.where(AnomalyEvent.rule_id == rule_id)
    if acknowledged is not None:
        stmt = stmt.where(AnomalyEvent.acknowledged.is_(acknowledged))
    stmt = stmt.order_by(AnomalyEvent.detected_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/orgs/{org_id}/anomaly-events/{event_id}/ack",
    response_model=AnomalyEventResponse,
)
async def acknowledge_anomaly_event(
    org_id: uuid.UUID,
    event_id: uuid.UUID,
    body: AnomalyEventAck = AnomalyEventAck(),
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnomalyEvent).where(
            AnomalyEvent.org_id == org_id,
            AnomalyEvent.id == event_id,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    event.acknowledged = True
    event.acknowledged_at = datetime.now(timezone.utc)
    event.acknowledged_by = body.acknowledged_by or user.email
    await db.commit()
    await db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# Evaluate on demand
# ---------------------------------------------------------------------------


class EvaluateResponse:
    """Small DTO returned by the on-demand evaluate endpoint."""

    def __init__(self, fired: int, rule_count: int):
        self.fired = fired
        self.rule_count = rule_count


@router.post(
    "/api/orgs/{org_id}/anomaly-rules/{rule_id}/evaluate",
    response_model=AnomalyEventResponse | None,
)
async def evaluate_anomaly_rule(
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    persist: bool = Query(
        True,
        description=(
            "If true, persist the resulting anomaly event. "
            "If false, return the would-be event without saving it "
            "(useful for \"what if\" previews)."
        ),
    ),
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    """Run the rule's detector against the current trace window."""
    result = await db.execute(
        select(AnomalyRule).where(
            AnomalyRule.org_id == org_id,
            AnomalyRule.id == rule_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")

    findings = await evaluate_org(db, org_id)
    match = next((f for f in findings if f.rule.id == rule_id and f.fired), None)
    if match is None:
        return None
    event = match.to_event()
    if persist:
        db.add(event)
        await db.commit()
        await db.refresh(event)
    return event


@router.post(
    "/api/orgs/{org_id}/anomaly-evaluate",
)
async def evaluate_all_rules(
    org_id: uuid.UUID,
    persist: bool = Query(True),
    user: User = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    """Run every enabled rule and return / persist the resulting events."""
    findings = await evaluate_org(db, org_id)
    fired = [f for f in findings if f.fired]
    if persist:
        for f in fired:
            db.add(f.to_event())
        await db.commit()
    return {
        "evaluated": len(findings),
        "fired": len(fired),
        "events": [
            {
                "rule_id": str(f.rule.id),
                "severity": f.severity,
                "message": f.message,
            }
            for f in fired
        ],
    }


__all__ = ["router"]
