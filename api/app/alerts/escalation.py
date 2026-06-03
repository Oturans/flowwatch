"""Escalation helpers.

Implements the "acknowledge-to-suppress" pattern:

  1. When an alert is sent, ``AlertLog`` records ``triggered_at``.
  2. The Celery Beat task ``check_escalation`` (defined in
     ``app.tasks.tasks``) scans for ``status='sent'`` alerts older than
     the per-source ``escalation.minutes_until_escalate`` threshold.
  3. For each, it re-sends the alert (via ``send_email_alert``) to the
     ``escalation.escalate_to`` recipients and stamps
     ``status='escalated'`` and ``escalated_at=now``.
  4. A user can call ``POST /api/alerts/{alert_id}/acknowledge`` to
     stamp ``acknowledged_at``; the escalation task filters those out.

The helpers here are kept as pure functions over the SQLAlchemy session
so they're easy to test without Celery.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_MINUTES_UNTIL_ESCALATE = 15
"""Default escalation threshold when the source hasn't configured one."""


def get_escalation_config(source: Any | None) -> dict[str, Any]:
    """Return the escalation config for *source*, falling back to defaults.

    Returns a dict with the keys:
        minutes_until_escalate (int)
        escalate_to            (list[str])
        enabled                (bool)
    """
    if source is None:
        return {
            "minutes_until_escalate": DEFAULT_MINUTES_UNTIL_ESCALATE,
            "escalate_to": [],
            "enabled": False,
        }
    cfg = getattr(source, "alert_config", None) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    esc = cfg.get("escalation") or {}
    if not isinstance(esc, dict):
        esc = {}
    minutes = esc.get("minutes_until_escalate", DEFAULT_MINUTES_UNTIL_ESCALATE)
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = DEFAULT_MINUTES_UNTIL_ESCALATE
    minutes = max(1, minutes)  # never less than 1 minute
    to = esc.get("escalate_to") or []
    if not isinstance(to, list):
        to = []
    to = [e for e in to if isinstance(e, str) and e]
    return {
        "minutes_until_escalate": minutes,
        "escalate_to": to,
        "enabled": esc.get("enabled", False) and bool(to),
    }


def find_alerts_to_escalate(
    session: Any,
    *,
    now: datetime | None = None,
    source_id: str | None = None,
) -> list[Any]:
    """Return AlertLog rows eligible for escalation.

    An alert is eligible if:
      * status == 'sent'
      * acknowledged_at is NULL
      * escalated_at is NULL
      * triggered_at is older than the per-source escalation threshold

    The threshold is read from each alert's source. Sources with no
    escalation config (or escalation.enabled=False) are skipped.

    ``source_id`` is an optional filter used by tests to scope the
    query; in production it's left as None so the Beat task finds
    every pending escalation.
    """
    from app.models import AlertLog, WebhookSource

    if now is None:
        now = datetime.now(timezone.utc)

    q = (
        session.query(AlertLog)
        .filter(AlertLog.status == "sent")
        .filter(AlertLog.acknowledged_at.is_(None))
        .filter(AlertLog.escalated_at.is_(None))
    )
    if source_id is not None:
        q = q.filter(AlertLog.source_id == source_id)
    candidates = q.all()

    out = []
    for alert in candidates:
        source = (
            session.query(WebhookSource)
            .filter_by(id=alert.source_id)
            .first()
        )
        cfg = get_escalation_config(source)
        if not cfg["enabled"]:
            continue
        # Make sure triggered_at is timezone-aware for comparison.
        triggered = alert.triggered_at
        if triggered is None:
            continue
        if triggered.tzinfo is None:
            triggered = triggered.replace(tzinfo=timezone.utc)
        if now - triggered >= timedelta(minutes=cfg["minutes_until_escalate"]):
            out.append(alert)
    return out
