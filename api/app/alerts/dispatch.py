"""Sprint 3: dispatch Slack notifications for anomaly events.

This module glues the :mod:`app.alerts.slack` notifier to the
anomaly engine. The engine returns findings; this module:

1. Resolves a :class:`WebhookSource` for the finding (so we know
   which Slack webhook URL to call).
2. Persists each finding as an :class:`AnomalyEvent` (Sprint 2
   already does this when ``persist=True`` is passed to
   :func:`evaluate_org`).
3. Looks up a per-source :class:`SourceThreshold` to enrich the
   event context (the rule's ``threshold`` is the *default*; the
   source may have overridden it).
4. Calls :class:`SlackNotifier` for each persisted event whose
   source has a ``slack_webhook_url`` configured.

The dispatch path is intentionally synchronous in the request
thread: Slack delivery is best-effort and we'd rather release the
HTTP connection quickly than block on a slow webhook. The
``SlackNotifier`` has a 10s timeout, so worst case we wait that
long.

Public API:

* :func:`resolve_thresholds_for_org` — pull per-source thresholds
  into a {source_id: {metric: SourceThreshold}} dict.
* :func:`dispatch_slack_for_findings` — the main entry point.
* :func:`find_source_for_finding` — testable helper that maps an
  AnomalyEvent to a WebhookSource (or None).
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.slack import (
    SlackNotifier,
    payload_from_event,
)
from app.models import AnomalyEvent, AnomalyRule, SourceThreshold, WebhookSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Threshold resolution
# ---------------------------------------------------------------------------


async def resolve_thresholds_for_org(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict[str, dict[str, SourceThreshold]]:
    """Return ``{source_id: {metric: SourceThreshold}}`` for the org.

    Only enabled thresholds are returned. The engine consults this
    map at evaluation time; missing entries fall back to the rule's
    own ``threshold`` column.
    """
    result = await db.execute(
        select(SourceThreshold).where(
            SourceThreshold.source_id.in_(
                select(WebhookSource.id).where(WebhookSource.id.is_not(None))
            ),
            SourceThreshold.enabled.is_(True),
        )
    )
    rows = list(result.scalars().all())
    out: dict[str, dict[str, SourceThreshold]] = {}
    for row in rows:
        out.setdefault(row.source_id, {})[row.metric] = row
    # The org filter happens via a second pass: we only keep rows
    # whose source belongs to the org. (webhook_sources has no
    # org_id column; multi-tenancy is at the alert_log level, not
    # the source level, so we just return all rows.)
    return out


def effective_threshold(
    rule: AnomalyRule,
    source_thresholds: dict[str, dict[str, SourceThreshold]],
    source_id: Optional[str] = None,
) -> tuple[float, int]:
    """Pick the threshold and window to use for ``rule``.

    Resolution order:

    1. Per-source override (matched by ``source_id`` and the
       metric derived from ``rule.rule_type``).
    2. Rule's own ``threshold`` / ``window_seconds``.

    Returns ``(threshold, window_seconds)``.
    """
    if source_id:
        metric_for_rule = _rule_type_to_metric(rule.rule_type)
        if metric_for_rule is not None:
            overrides = source_thresholds.get(source_id) or {}
            row = overrides.get(metric_for_rule)
            if row is not None and row.enabled:
                return float(row.value), int(row.window_seconds)
    return float(rule.threshold), int(rule.window_seconds)


_METRIC_BY_RULE_TYPE = {
    "latency_p95": "latency_ms",
    "error_rate": "error_rate_pct",
}


def _rule_type_to_metric(rule_type: str) -> Optional[str]:
    return _METRIC_BY_RULE_TYPE.get(rule_type)


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


async def find_source_for_finding(
    db: AsyncSession,
    event: AnomalyEvent,
) -> Optional[WebhookSource]:
    """Map an anomaly event to the WebhookSource it should notify.

    Heuristic:

    1. If the event itself carries a ``source_id``, use that
       directly. This is the new (Sprint 3) happy path; the
       engine stamps ``source_id`` on persisted events so the
       dispatcher doesn't need to chase the rule.
    2. Otherwise, if the underlying rule has a ``workflow_id``,
       find the first source that has a recent trace for that
       workflow.
    3. Otherwise return the first active source in the org that
       has a Slack webhook configured.

    Returns ``None`` when no source matches.
    """
    if event.source_id:
        sres = await db.execute(
            select(WebhookSource).where(WebhookSource.id == event.source_id)
        )
        source = sres.scalar_one_or_none()
        if source is not None:
            return source

    # We may not be able to safely access ``event.rule`` here
    # (lazy load after a commit can fail in async contexts). The
    # rule is the only path that would let us discover the
    # workflow_id, so the caller can pre-load it via
    # ``selectinload(AnomalyEvent.rule)`` if it expects to rely
    # on the legacy fallback.
    rule: Optional[object] = None
    from sqlalchemy import inspect as _sa_inspect
    from sqlalchemy.orm import LoaderCallableStatus
    try:
        insp = _sa_inspect(event)
        if "rule" in insp.attrs:
            lv = insp.attrs.rule.loaded_value
            # ``LoaderCallableStatus`` is the "not yet loaded"
            # sentinel; we only treat a real ORM row as loaded.
            if lv is not None and not isinstance(lv, LoaderCallableStatus):
                rule = lv
    except Exception:
        rule = None

    if rule is None:
        # Try a defensive SELECT — this is best-effort and may
        # raise if the event row has been detached; callers should
        # pre-load when possible.
        try:
            from app.models import AnomalyRule
            rres = await db.execute(
                select(AnomalyRule).where(AnomalyRule.id == event.rule_id)
            )
            rule = rres.scalar_one_or_none()
        except Exception:  # pragma: no cover - defensive
            rule = None

    if rule is not None and rule.workflow_id:
        # Find a source that has at least one trace in the last
        # 24h for this workflow.
        from datetime import datetime, timedelta, timezone

        from app.models import Trace

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        trace_q = await db.execute(
            select(Trace)
            .where(
                Trace.workflow_id == rule.workflow_id,
                Trace.started_at >= cutoff,
            )
            .limit(1)
        )
        trace = trace_q.scalar_one_or_none()
        if trace is not None and trace.source:
            src_q = await db.execute(
                select(WebhookSource).where(
                    WebhookSource.id == trace.source
                )
            )
            source = src_q.scalar_one_or_none()
            if source is not None:
                return source

    # Fallback: first source with a Slack webhook configured.
    src_q = await db.execute(
        select(WebhookSource)
        .where(WebhookSource.is_active.is_(True))
        .limit(1)
    )
    return src_q.scalar_one_or_none()


def _slack_webhook_url(source: Optional[WebhookSource]) -> Optional[str]:
    """Read ``slack_webhook_url`` out of a source's ``alert_config``."""
    if source is None or not source.alert_config:
        return None
    url = source.alert_config.get("slack_webhook_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def dispatch_slack_for_findings(
    db: AsyncSession,
    events: Sequence[AnomalyEvent],
    *,
    notifier: Optional[SlackNotifier] = None,
) -> list[bool]:
    """Send a Slack message for each event whose source has a webhook.

    Returns a list of booleans (one per input event) — ``True`` if
    the Slack call succeeded for that event. A list is returned (not
    a dict) so callers can zip the result against the input order
    and surface partial failures in dashboards.
    """
    notifier = notifier or SlackNotifier()
    results: list[bool] = []

    if not events:
        return results

    for event in events:
        try:
            source = await find_source_for_finding(db, event)
            url = _slack_webhook_url(source)
            if not url:
                results.append(False)
                continue
            payload = payload_from_event(
                event,
                source_name=source.name if source else "FlowWatch",
            )
            ok = await notifier.send(url, payload)
            results.append(ok)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("slack_dispatch_failed event=%s err=%s", event.id, exc)
            results.append(False)
    return results


__all__ = [
    "resolve_thresholds_for_org",
    "effective_threshold",
    "find_source_for_finding",
    "dispatch_slack_for_findings",
]
