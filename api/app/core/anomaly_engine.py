"""Sprint 2: anomaly detection engine.

This module is the *pure* logic. The HTTP layer lives in
``app.routes.anomalies``. The split keeps the engine easy to unit
test without a database or a network.

The engine is invoked after a trace is persisted (via the
``evaluate_recent_traces`` background task) and on a schedule by
the Celery beat. For Sprint 2 we only implement the synchronous
"evaluate now" path; the periodic scheduler is a follow-up.

Detectors
---------

Three rule types are supported:

* ``latency_p95`` — p95 of trace durations in the window is
  greater than the rule's ``threshold`` (milliseconds).
* ``error_rate`` — fraction of errored traces in the window is
  greater than ``threshold`` (interpreted as a percentage
  between 0 and 100).
* ``throughput_drop`` — the number of traces in the window
  divided by the window length in seconds is less than
  ``threshold`` traces/sec.

Each rule is scoped to an org, optional workflow, and a sliding
window. The engine returns a list of (rule, anomaly_event)
records. Callers (the API + the Celery task) are responsible
for persisting the events.
"""

from __future__ import annotations

import logging
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnomalyEvent, AnomalyRule, Trace
from app.models.observability import (
    RULE_ERROR_RATE,
    RULE_LATENCY_P95,
    RULE_THROUGHPUT_DROP,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class EngineContext:
    """Inputs the engine needs from the caller.

    Pulled out of the database once per evaluation so the detectors
    stay pure functions of (rule, traces).
    """

    org_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    traces: list[Trace] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """A single anomaly finding (or a benign "rule evaluated OK" record)."""

    rule: AnomalyRule
    fired: bool
    severity: str
    message: str
    metric_value: Optional[float] = None
    context: Optional[dict] = None

    def to_event(self) -> AnomalyEvent:
        """Build (but do not persist) the AnomalyEvent ORM row."""
        return AnomalyEvent(
            org_id=self.rule.org_id,
            rule_id=self.rule.id,
            severity=self.severity,
            message=self.message,
            context={
                **(self.context or {}),
                "metric_value": self.metric_value,
                "rule_type": self.rule.rule_type,
                "threshold": self.rule.threshold,
                "window_seconds": self.rule.window_seconds,
            },
        )


# ---------------------------------------------------------------------------
# Pure detector functions
# ---------------------------------------------------------------------------


def detect_latency_p95(traces: Sequence[Trace], threshold_ms: float) -> Optional[EvaluationResult]:
    """Fire when p95 duration exceeds ``threshold_ms``.

    We need at least 5 samples to call the p95 statistically
    meaningful. With fewer, we return ``None`` (don't fire).
    """
    durations = [t.duration_ms for t in traces if t.duration_ms is not None]
    if len(durations) < 5:
        return None
    p95 = _percentile(durations, 95.0)
    if p95 > threshold_ms:
        return EvaluationResult(
            # ``rule`` is filled in by the caller; we return a partial
            # marker. The actual ``rule`` field is set by the
            # orchestrator. We use a tiny helper attribute to flag
            # partials.
            rule=None,  # type: ignore[arg-type]
            fired=True,
            severity="high" if p95 > threshold_ms * 1.5 else "medium",
            message=(
                f"p95 latency {p95:.0f}ms exceeds threshold {threshold_ms:.0f}ms "
                f"(n={len(durations)})"
            ),
            metric_value=p95,
            context={"p95_ms": p95, "samples": len(durations)},
        )
    return None


def detect_error_rate(traces: Sequence[Trace], threshold_pct: float) -> Optional[EvaluationResult]:
    """Fire when error rate (in percent) exceeds ``threshold_pct``."""
    if not traces:
        return None
    errors = sum(1 for t in traces if t.status == "error")
    rate_pct = (errors / len(traces)) * 100.0
    if rate_pct > threshold_pct:
        return EvaluationResult(
            rule=None,  # type: ignore[arg-type]
            fired=True,
            severity="high" if rate_pct > threshold_pct * 1.5 else "medium",
            message=(
                f"Error rate {rate_pct:.1f}% exceeds threshold {threshold_pct:.1f}% "
                f"({errors}/{len(traces)})"
            ),
            metric_value=rate_pct,
            context={"errors": errors, "total": len(traces)},
        )
    return None


def detect_throughput_drop(
    traces: Sequence[Trace],
    threshold_per_sec: float,
    window_seconds: int,
) -> Optional[EvaluationResult]:
    """Fire when throughput (traces/sec) is below ``threshold_per_sec``."""
    if window_seconds <= 0:
        return None
    actual = len(traces) / window_seconds
    if actual < threshold_per_sec:
        return EvaluationResult(
            rule=None,  # type: ignore[arg-type]
            fired=True,
            severity="medium",
            message=(
                f"Throughput {actual:.3f}/s is below threshold {threshold_per_sec:.3f}/s "
                f"({len(traces)} traces in {window_seconds}s)"
            ),
            metric_value=actual,
            context={"window_seconds": window_seconds, "trace_count": len(traces)},
        )
    return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


# Map rule type -> detector function. The detector's first positional
# arg is the list of traces; the rest are pulled from the rule.
DETECTORS = {
    RULE_LATENCY_P95: (detect_latency_p95, ["threshold"]),
    RULE_ERROR_RATE: (detect_error_rate, ["threshold"]),
    RULE_THROUGHPUT_DROP: (
        detect_throughput_drop,
        ["threshold", "window_seconds"],
    ),
}


async def _load_recent_traces(
    db: AsyncSession,
    org_id: uuid.UUID,
    window_start: datetime,
    workflow_id: Optional[str] = None,
) -> list[Trace]:
    """Return traces in [window_start, now] for the org/workflow."""
    stmt = select(Trace).where(
        Trace.org_id == org_id,
        Trace.started_at >= window_start,
    )
    if workflow_id is not None:
        stmt = stmt.where(Trace.workflow_id == workflow_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def evaluate_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    as_of: Optional[datetime] = None,
) -> list[EvaluationResult]:
    """Evaluate every enabled rule for the org.

    ``as_of`` defaults to ``datetime.now(UTC)``. Tests use it to
    pin the window.
    """
    as_of = as_of or datetime.now(timezone.utc)

    # Load all enabled rules for the org in a single query.
    rules_result = await db.execute(
        select(AnomalyRule).where(
            AnomalyRule.org_id == org_id,
            AnomalyRule.enabled.is_(True),
        )
    )
    rules = list(rules_result.scalars().all())
    if not rules:
        return []

    # Group rules by (workflow_id, window_seconds) so we load the
    # trace window once and reuse it across rules.
    grouped: dict[tuple[Optional[str], int], list[AnomalyRule]] = {}
    for r in rules:
        grouped.setdefault((r.workflow_id, r.window_seconds), []).append(r)

    findings: list[EvaluationResult] = []
    for (workflow_id, window_seconds), bucket in grouped.items():
        window_start = as_of - timedelta(seconds=window_seconds)
        traces = await _load_recent_traces(db, org_id, window_start, workflow_id)
        for rule in bucket:
            result = _apply_rule(rule, traces)
            if result is not None:
                findings.append(result)
    return findings


def _apply_rule(rule: AnomalyRule, traces: Sequence[Trace]) -> Optional[EvaluationResult]:
    """Dispatch a single rule to its detector."""
    detector, _ = DETECTORS.get(rule.rule_type, (None, None))
    if detector is None:
        logger.warning("unknown rule_type=%s for rule=%s", rule.rule_type, rule.id)
        return None
    if rule.rule_type == RULE_LATENCY_P95:
        result = detector(traces, rule.threshold)
    elif rule.rule_type == RULE_ERROR_RATE:
        result = detector(traces, rule.threshold)
    elif rule.rule_type == RULE_THROUGHPUT_DROP:
        result = detector(traces, rule.threshold, rule.window_seconds)
    else:
        return None
    if result is None:
        return None
    result.rule = rule
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(values: Sequence[float], pct: float) -> float:
    """Return the pct-th percentile of ``values`` (0 <= pct <= 100).

    Uses linear interpolation between closest ranks. Returns 0 for
    empty input.
    """
    if not values:
        return 0.0
    sorted_v = sorted(values)
    if len(sorted_v) == 1:
        return float(sorted_v[0])
    k = (len(sorted_v) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_v) - 1)
    if f == c:
        return float(sorted_v[f])
    return sorted_v[f] + (sorted_v[c] - sorted_v[f]) * (k - f)


__all__ = [
    "EngineContext",
    "EvaluationResult",
    "detect_latency_p95",
    "detect_error_rate",
    "detect_throughput_drop",
    "evaluate_org",
    "DETECTORS",
]
