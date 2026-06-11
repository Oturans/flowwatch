"""Sprint 3: v1 alert management API.

Endpoints (mounted under ``/api/v1/``):

* ``PATCH   /sources/{source_id}/thresholds``        — replace thresholds
* ``GET     /sources/{source_id}/thresholds``        — list thresholds
* ``POST    /sources/{source_id}/slack-config``      — set Slack webhook
* ``GET     /sources/{source_id}/slack-config``      — read Slack config
* ``GET     /alerts``                               — paginated alert list
* ``PATCH   /alerts/{alert_id}/acknowledge``         — mark acknowledged
* ``PATCH   /alerts/{alert_id}/dismiss``             — mark dismissed
* ``POST    /alerts/{alert_id}/test-slack``          — send a test Slack

Why a separate v1 prefix?

The existing routes under ``/api/`` and ``/api/orgs/...`` are
versioned implicitly by their request shape. The Sprint 3 spec
asks for ``/api/v1/...`` paths so the dashboard can target a
single, stable contract. We don't move the old routes — they
stay in place for backward compat — but new features live here.

Authentication: the v1 router is mounted behind the same
``get_current_user`` dependency the rest of the app uses. We
require that the source/alert belong to the user's org when
``org_id`` is available on the row. WebhookSource does not carry
an org_id directly, so we enforce membership at the ``User.org_id``
level via the existing ``require_org_member`` helper, passing the
user's own org. That keeps the v1 surface usable from the
single-tenant login flow without an extra lookup.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.dispatch import find_source_for_finding
from app.alerts.slack import (
    SlackNotifier,
    SlackPayload,
)
from app.core.auth import get_current_user
from app.database import get_db
from app.models import (
    AnomalyEvent,
    SourceThreshold,
    VALID_THRESHOLD_METRICS,
    WebhookSource,
    User,
)
from app.schemas.sprint3 import (
    AlertAckRequest,
    AlertDismissRequest,
    AlertListItem,
    AlertListResponse,
    SlackConfigResponse,
    SlackConfigUpdate,
    ThresholdResponse,
    ThresholdsResponse,
    ThresholdsUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["sprint3"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def require_authenticated_user(
    user: User = Depends(get_current_user),
) -> User:
    """Just require a logged-in user. Per-source ownership is checked
    inside each handler because the existing schema doesn't carry
    org_id on WebhookSource."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )
    return user


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


def _threshold_to_response(row: SourceThreshold) -> ThresholdResponse:
    return ThresholdResponse(
        metric=row.metric,
        value=float(row.value),
        window_seconds=int(row.window_seconds),
        enabled=bool(row.enabled),
        updated_at=row.updated_at,
    )


@router.get(
    "/sources/{source_id}/thresholds",
    response_model=ThresholdsResponse,
)
async def get_source_thresholds(
    source_id: str,
    user: User = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    # Existence check; we don't read any field off the source row.
    await _get_source_or_404(db, source_id)
    rows = await _list_thresholds(db, source_id)
    return ThresholdsResponse(
        source_id=source_id,
        thresholds=[_threshold_to_response(r) for r in rows],
    )


@router.patch(
    "/sources/{source_id}/thresholds",
    response_model=ThresholdsResponse,
)
async def update_source_thresholds(
    source_id: str,
    body: ThresholdsUpdate,
    user: User = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the source's threshold set.

    The body is a *full* list of metric/value pairs; anything
    currently stored but not in the body is removed. This is
    simpler than a partial PATCH and matches the dashboard UI
    ("save all sliders" pattern).
    """
    # Verify the source exists before mutating thresholds. We
    # don't read any field off the row; the existence check is
    # the whole point.
    await _get_source_or_404(db, source_id)

    # Drop existing rows for the source.
    existing = await db.execute(
        select(SourceThreshold).where(SourceThreshold.source_id == source_id)
    )
    for row in existing.scalars().all():
        await db.delete(row)
    await db.flush()

    # Insert the new set. We could UPSERT in a single SQL statement
    # but the explicit delete+insert is easier to reason about and
    # the cardinality is tiny (3 rows max).
    new_rows: list[SourceThreshold] = []
    for item in body.thresholds:
        if item.metric not in VALID_THRESHOLD_METRICS:
            # Pydantic already validates this, but the SQL CHECK
            # constraint will reject it too. Defensive guard.
            raise HTTPException(
                status_code=400,
                detail=f"invalid metric '{item.metric}'",
            )
        row = SourceThreshold(
            source_id=source_id,
            metric=item.metric,
            value=float(item.value),
            window_seconds=int(item.window_seconds),
            enabled=bool(item.enabled),
        )
        db.add(row)
        new_rows.append(row)
    await db.commit()
    for row in new_rows:
        await db.refresh(row)

    return ThresholdsResponse(
        source_id=source_id,
        thresholds=[_threshold_to_response(r) for r in new_rows],
    )


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


def _read_slack_config(source: WebhookSource) -> SlackConfigResponse:
    cfg = source.alert_config or {}
    url = cfg.get("slack_webhook_url") if isinstance(cfg, dict) else None
    return SlackConfigResponse(
        source_id=source.id,
        webhook_url_set=isinstance(url, str) and bool(url.strip()),
        enabled=bool(cfg.get("slack_enabled", True)) if isinstance(cfg, dict) else True,
        channel_hint=(cfg.get("slack_channel_hint") if isinstance(cfg, dict) else None),
    )


@router.get(
    "/sources/{source_id}/slack-config",
    response_model=SlackConfigResponse,
)
async def get_slack_config(
    source_id: str,
    user: User = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    source = await _get_source_or_404(db, source_id)
    return _read_slack_config(source)


@router.post(
    "/sources/{source_id}/slack-config",
    response_model=SlackConfigResponse,
)
async def set_slack_config(
    source_id: str,
    body: SlackConfigUpdate,
    user: User = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear a Slack webhook for a source.

    Pass ``webhook_url=""`` to clear the configuration entirely.
    """
    source = await _get_source_or_404(db, source_id)
    cfg: dict = dict(source.alert_config or {})

    if body.webhook_url is not None:
        if body.webhook_url == "":
            cfg.pop("slack_webhook_url", None)
        else:
            cfg["slack_webhook_url"] = body.webhook_url

    cfg["slack_enabled"] = bool(body.enabled)

    if body.channel_hint is not None:
        if body.channel_hint == "":
            cfg.pop("slack_channel_hint", None)
        else:
            cfg["slack_channel_hint"] = body.channel_hint

    source.alert_config = cfg
    await db.commit()
    await db.refresh(source)
    return _read_slack_config(source)


@router.post(
    "/alerts/{alert_id}/test-slack",
    response_model=dict,
)
async def test_slack_for_alert(
    alert_id: uuid.UUID,
    user: User = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a "this is what an alert would look like" message to the
    source's Slack webhook. Useful from the dashboard's "Send test
    message" button.
    """
    event = await _get_alert_or_404(db, alert_id)
    # Prefer the source_id stamped on the event itself; fall back
    # to the rule/workflow resolver for legacy events.
    source: Optional[WebhookSource] = None
    if event.source_id:
        sres = await db.execute(
            select(WebhookSource).where(WebhookSource.id == event.source_id)
        )
        source = sres.scalar_one_or_none()
    if source is None:
        source = await find_source_for_finding(db, event)
    if source is None:
        raise HTTPException(status_code=404, detail="no source for this alert")
    cfg = source.alert_config or {}
    url = cfg.get("slack_webhook_url") if isinstance(cfg, dict) else None
    if not (isinstance(url, str) and url.strip()):
        raise HTTPException(
            status_code=409,
            detail="source has no Slack webhook configured",
        )

    # Use a synthetic "test" message so the recipient knows it's
    # not a real alert.
    test_payload = SlackPayload(
        source_name=f"{source.name} (test)",
        metric="latency_ms",
        value=0.0,
        threshold=0.0,
        severity="low",
        timestamp=datetime.now(timezone.utc).isoformat(),
        message="This is a test notification from FlowWatch.",
    )
    notifier = SlackNotifier()
    ok = await notifier.send(url, test_payload)
    return {
        "alert_id": str(alert_id),
        "source_id": source.id,
        "sent": ok,
    }


# ---------------------------------------------------------------------------
# Alert history
# ---------------------------------------------------------------------------


def _event_to_list_item(
    event: AnomalyEvent,
    source: Optional[WebhookSource],
    rule_name: Optional[str],
) -> AlertListItem:
    # Derive status: dismissed > acknowledged > open.
    if event.dismissed:
        status_label = "dismissed"
    elif event.acknowledged:
        status_label = "acknowledged"
    else:
        status_label = "open"
    return AlertListItem(
        id=event.id,
        source_id=event.source_id or (source.id if source else ""),
        source_name=source.name if source else None,
        rule_id=event.rule_id,
        rule_name=rule_name,
        severity=event.severity,
        status=status_label,
        message=event.message,
        context=event.context,
        detected_at=event.detected_at,
        acknowledged_at=event.acknowledged_at,
        acknowledged_by=event.acknowledged_by,
        dismissed_at=event.dismissed_at,
        dismissed_by=event.dismissed_by,
    )


@router.get(
    "/alerts",
    response_model=AlertListResponse,
)
async def list_alerts(
    source_id: Optional[str] = Query(
        None, description="Filter by webhook source id"
    ),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="open | acknowledged | dismissed",
    ),
    severity: Optional[str] = Query(
        None, description="low | medium | high | critical"
    ),
    start: Optional[datetime] = Query(
        None, description="Inclusive lower bound on detected_at"
    ),
    end: Optional[datetime] = Query(
        None, description="Inclusive upper bound on detected_at"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """List alerts with filters and pagination.

    Results are scoped to the user's org (via
    ``AnomalyEvent.org_id``). The ``status`` filter maps to the
    derived ``(acknowledged, dismissed)`` columns:

    * ``open``         — NOT acknowledged AND NOT dismissed
    * ``acknowledged`` — acknowledged AND NOT dismissed
    * ``dismissed``    — dismissed (overrides acknowledged)
    """
    stmt = select(AnomalyEvent).where(AnomalyEvent.org_id == user.org_id)
    count_stmt = select(func.count(AnomalyEvent.id)).where(
        AnomalyEvent.org_id == user.org_id
    )

    if source_id is not None:
        stmt = stmt.where(AnomalyEvent.source_id == source_id)
        count_stmt = count_stmt.where(AnomalyEvent.source_id == source_id)
    if severity:
        stmt = stmt.where(AnomalyEvent.severity == severity)
        count_stmt = count_stmt.where(AnomalyEvent.severity == severity)
    if start:
        stmt = stmt.where(AnomalyEvent.detected_at >= start)
        count_stmt = count_stmt.where(AnomalyEvent.detected_at >= start)
    if end:
        stmt = stmt.where(AnomalyEvent.detected_at <= end)
        count_stmt = count_stmt.where(AnomalyEvent.detected_at <= end)
    if status_filter:
        if status_filter == "open":
            stmt = stmt.where(
                AnomalyEvent.acknowledged.is_(False),
                AnomalyEvent.dismissed.is_(False),
            )
            count_stmt = count_stmt.where(
                AnomalyEvent.acknowledged.is_(False),
                AnomalyEvent.dismissed.is_(False),
            )
        elif status_filter == "acknowledged":
            stmt = stmt.where(
                AnomalyEvent.acknowledged.is_(True),
                AnomalyEvent.dismissed.is_(False),
            )
            count_stmt = count_stmt.where(
                AnomalyEvent.acknowledged.is_(True),
                AnomalyEvent.dismissed.is_(False),
            )
        elif status_filter == "dismissed":
            stmt = stmt.where(AnomalyEvent.dismissed.is_(True))
            count_stmt = count_stmt.where(AnomalyEvent.dismissed.is_(True))
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown status filter '{status_filter}'; "
                    "expected: open | acknowledged | dismissed"
                ),
            )

    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.order_by(AnomalyEvent.detected_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > page_size
    rows = rows[:page_size]

    # Batch-load sources and rules to avoid N+1.
    source_ids = {r.source_id for r in rows if r.source_id}
    rule_ids = {r.rule_id for r in rows}
    sources: dict[str, WebhookSource] = {}
    rules_map: dict[uuid.UUID, str] = {}
    if source_ids:
        sres = await db.execute(
            select(WebhookSource).where(WebhookSource.id.in_(source_ids))
        )
        sources = {s.id: s for s in sres.scalars().all()}
    if rule_ids:
        from app.models import AnomalyRule
        rres = await db.execute(
            select(AnomalyRule).where(AnomalyRule.id.in_(rule_ids))
        )
        rules_map = {r.id: r.name for r in rres.scalars().all()}

    items = [
        _event_to_list_item(
            r,
            sources.get(r.source_id) if r.source_id else None,
            rules_map.get(r.rule_id),
        )
        for r in rows
    ]
    return AlertListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.patch(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertListItem,
)
async def acknowledge_alert_v1(
    alert_id: uuid.UUID,
    body: AlertAckRequest = AlertAckRequest(),
    user: User = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    event = await _get_alert_or_404(db, alert_id)
    if not event.acknowledged:
        event.acknowledged = True
        event.acknowledged_at = datetime.now(timezone.utc)
        event.acknowledged_by = body.acknowledged_by or user.email
        await db.commit()
        await db.refresh(event)
    source = await _maybe_source(db, event)
    return _event_to_list_item(event, source, None)


@router.patch(
    "/alerts/{alert_id}/dismiss",
    response_model=AlertListItem,
)
async def dismiss_alert(
    alert_id: uuid.UUID,
    body: AlertDismissRequest = AlertDismissRequest(),
    user: User = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    event = await _get_alert_or_404(db, alert_id)
    if not event.dismissed:
        event.dismissed = True
        event.dismissed_at = datetime.now(timezone.utc)
        event.dismissed_by = body.dismissed_by or user.email
        await db.commit()
        await db.refresh(event)
    source = await _maybe_source(db, event)
    return _event_to_list_item(event, source, None)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _get_source_or_404(
    db: AsyncSession, source_id: str
) -> WebhookSource:
    result = await db.execute(
        select(WebhookSource).where(WebhookSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source


async def _get_alert_or_404(
    db: AsyncSession, alert_id: uuid.UUID
) -> AnomalyEvent:
    result = await db.execute(
        select(AnomalyEvent).where(AnomalyEvent.id == alert_id)
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return event


async def _list_thresholds(
    db: AsyncSession, source_id: str
) -> list[SourceThreshold]:
    result = await db.execute(
        select(SourceThreshold)
        .where(SourceThreshold.source_id == source_id)
        .order_by(SourceThreshold.metric)
    )
    return list(result.scalars().all())


async def _maybe_source(
    db: AsyncSession, event: AnomalyEvent
) -> Optional[WebhookSource]:
    if not event.source_id:
        return None
    result = await db.execute(
        select(WebhookSource).where(WebhookSource.id == event.source_id)
    )
    return result.scalar_one_or_none()


__all__ = ["router"]
