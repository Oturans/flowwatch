"""Sprint 2: anomaly detection engine + API tests.

Covers:

* ``anomaly_engine`` pure detectors (no DB) — fast, deterministic.
* ``anomaly_engine.evaluate_org`` against seeded traces.
* REST CRUD for rules + events.
* On-demand evaluation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.anomaly_engine import (
    DETECTORS,
    detect_error_rate,
    detect_latency_p95,
    detect_throughput_drop,
    evaluate_org,
)
from app.database import AsyncSessionLocal
from app.models import AnomalyEvent, AnomalyRule, Trace
from app.models.observability import (
    RULE_ERROR_RATE,
    RULE_LATENCY_P95,
    RULE_THROUGHPUT_DROP,
    VALID_RULE_TYPES,
)


# ---------------------------------------------------------------------------
# Engine: pure detector tests (no DB)
# ---------------------------------------------------------------------------


def _t(trace_id: str, duration_ms: int | None = None, status: str = "ok") -> Trace:
    """Build an in-memory Trace without going through the DB."""
    return Trace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        trace_id=trace_id,
        name="t",
        status=status,
        started_at=datetime.now(timezone.utc),
        duration_ms=duration_ms,
    )


class TestLatencyP95:
    def test_below_threshold_does_not_fire(self):
        traces = [_t(f"t{i}", duration_ms=100 + i) for i in range(20)]
        assert detect_latency_p95(traces, threshold_ms=1000) is None

    def test_above_threshold_fires(self):
        traces = [_t(f"t{i}", duration_ms=1000 + i * 100) for i in range(20)]
        result = detect_latency_p95(traces, threshold_ms=500)
        assert result is not None
        assert result.fired is True
        assert "p95" in result.message
        assert result.metric_value is not None and result.metric_value > 500

    def test_too_few_samples_does_not_fire(self):
        # With <5 samples the detector stays silent
        traces = [_t("a", 10000), _t("b", 12000)]
        assert detect_latency_p95(traces, threshold_ms=100) is None

    def test_severity_scales_with_overshoot(self):
        # 2x threshold -> high
        traces = [_t(f"t{i}", duration_ms=1000 + i) for i in range(20)]
        result = detect_latency_p95(traces, threshold_ms=500)
        assert result is not None
        assert result.severity == "high"

        # Mild overshoot -> medium
        traces = [_t(f"t{i}", duration_ms=200 + i) for i in range(20)]
        result = detect_latency_p95(traces, threshold_ms=150)
        assert result is not None
        assert result.severity == "medium"


class TestErrorRate:
    def test_no_traces_no_fire(self):
        assert detect_error_rate([], threshold_pct=10) is None

    def test_below_threshold_no_fire(self):
        traces = [_t("a", status="ok")] * 8 + [_t("b", status="error")] * 2
        # 20% error rate, threshold 50%
        assert detect_error_rate(traces, threshold_pct=50) is None

    def test_above_threshold_fires(self):
        traces = [_t("a", status="ok")] * 5 + [_t("b", status="error")] * 5
        # 50% error rate, threshold 10%
        result = detect_error_rate(traces, threshold_pct=10)
        assert result is not None
        assert result.metric_value == 50.0
        assert "50.0%" in result.message


class TestThroughputDrop:
    def test_above_threshold_no_fire(self):
        # 10 traces in 60s = 0.166/s, threshold 0.1/s
        traces = [_t(f"t{i}") for i in range(10)]
        assert (
            detect_throughput_drop(traces, threshold_per_sec=0.1, window_seconds=60)
            is None
        )

    def test_below_threshold_fires(self):
        traces = [_t("a"), _t("b")]
        result = detect_throughput_drop(
            traces, threshold_per_sec=10, window_seconds=60
        )
        assert result is not None
        assert result.metric_value is not None
        assert result.metric_value < 10

    def test_zero_window_returns_none(self):
        assert (
            detect_throughput_drop([_t("a")], threshold_per_sec=0.1, window_seconds=0)
            is None
        )


# ---------------------------------------------------------------------------
# Engine: evaluate_org (DB-bound)
# ---------------------------------------------------------------------------


async def _seed_traces(org_id, durations: list[int], statuses: list[str] | None = None):
    statuses = statuses or ["ok"] * len(durations)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        for i, (d, s) in enumerate(zip(durations, statuses)):
            session.add(Trace(
                org_id=org_id,
                trace_id=f"seed-{i}",
                name="seed",
                status=s,
                started_at=now - timedelta(seconds=i),
                duration_ms=d,
            ))
        await session.commit()


async def _make_rule(tenant, **kwargs) -> AnomalyRule:
    defaults = dict(
        name="default-rule",
        rule_type=RULE_LATENCY_P95,
        threshold=500.0,
        window_seconds=300,
        workflow_id=None,
        enabled=True,
    )
    defaults.update(kwargs)
    rule = AnomalyRule(org_id=tenant.id, **defaults)
    async with AsyncSessionLocal() as session:
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
    return rule


class TestEvaluateOrg:
    async def test_no_rules_returns_empty(self, tenant_factory):
        tenant = await tenant_factory(name="Eval NoRules")
        async with AsyncSessionLocal() as session:
            findings = await evaluate_org(session, tenant.id)
        assert findings == []

    async def test_latency_p95_fires(self, tenant_factory):
        tenant = await tenant_factory(name="Eval Latency")
        await _make_rule(tenant, threshold=500)
        # 10 slow traces in the window
        await _seed_traces(tenant.id, [1000] * 10)
        async with AsyncSessionLocal() as session:
            findings = await evaluate_org(session, tenant.id)
        assert len(findings) == 1
        assert findings[0].fired is True
        assert findings[0].rule.rule_type == RULE_LATENCY_P95

    async def test_error_rate_fires(self, tenant_factory):
        tenant = await tenant_factory(name="Eval Error")
        await _make_rule(tenant, rule_type=RULE_ERROR_RATE, threshold=10.0)
        # 5 ok + 5 errored = 50% error rate
        await _seed_traces(
            tenant.id,
            [100] * 10,
            ["ok"] * 5 + ["error"] * 5,
        )
        async with AsyncSessionLocal() as session:
            findings = await evaluate_org(session, tenant.id)
        assert len(findings) == 1
        assert findings[0].fired is True
        assert findings[0].rule.rule_type == RULE_ERROR_RATE

    async def test_disabled_rule_does_not_evaluate(self, tenant_factory):
        tenant = await tenant_factory(name="Eval Disabled")
        await _make_rule(tenant, threshold=500, enabled=False)
        await _seed_traces(tenant.id, [1000] * 10)
        async with AsyncSessionLocal() as session:
            findings = await evaluate_org(session, tenant.id)
        assert findings == []

    async def test_throughput_drop_fires(self, tenant_factory):
        tenant = await tenant_factory(name="Eval Throughput")
        # window=60s, threshold=5/s
        await _make_rule(
            tenant,
            rule_type=RULE_THROUGHPUT_DROP,
            threshold=5.0,
            window_seconds=60,
        )
        # 2 traces in the last 60s = 0.033/s << 5/s
        await _seed_traces(tenant.id, [100, 100])
        async with AsyncSessionLocal() as session:
            findings = await evaluate_org(session, tenant.id)
        assert len(findings) == 1
        assert findings[0].fired is True

    async def test_all_three_rule_types_present(self):
        assert set(DETECTORS.keys()) == set(VALID_RULE_TYPES)
        assert RULE_LATENCY_P95 in VALID_RULE_TYPES
        assert RULE_ERROR_RATE in VALID_RULE_TYPES
        assert RULE_THROUGHPUT_DROP in VALID_RULE_TYPES


# ---------------------------------------------------------------------------
# REST: rules CRUD
# ---------------------------------------------------------------------------


async def test_create_and_list_rule(client, tenant_factory, auth_headers_factory):
    tenant = await tenant_factory(name="REST Create")
    # Create an admin user for this tenant
    from app.core.auth import create_access_token
    from app.models import User
    from app.core.auth import hash_password
    async with AsyncSessionLocal() as session:
        user = User(
            email="rest-create@example.com",
            hashed_password=hash_password("hunter2hunter2"),
            org_id=tenant.id,
            role="admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    h = await auth_headers_factory(user)

    r = await client.post(
        f"/api/orgs/{tenant.id}/anomaly-rules",
        json={
            "name": "p95 latency",
            "rule_type": RULE_LATENCY_P95,
            "threshold": 750.0,
            "window_seconds": 300,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "p95 latency"
    assert body["rule_type"] == RULE_LATENCY_P95
    assert body["threshold"] == 750.0

    # List
    r2 = await client.get(f"/api/orgs/{tenant.id}/anomaly-rules", headers=h)
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]


async def test_create_rule_with_invalid_type_returns_400(
    client, tenant_factory, user_factory, auth_headers_factory
):
    tenant = await tenant_factory(name="REST BadType")
    u = await user_factory(tenant, email="rest-bad@example.com")
    h = await auth_headers_factory(u)
    r = await client.post(
        f"/api/orgs/{tenant.id}/anomaly-rules",
        json={"name": "x", "rule_type": "not_a_real_type", "threshold": 1.0},
        headers=h,
    )
    assert r.status_code == 422


async def test_cross_tenant_rule_access_forbidden(
    client, tenant_factory, user_factory, auth_headers_factory
):
    t1 = await tenant_factory(name="REST XRef 1")
    t2 = await tenant_factory(name="REST XRef 2")
    u1 = await user_factory(t1, email="xref@example.com")
    h1 = await auth_headers_factory(u1)
    r = await client.get(f"/api/orgs/{t2.id}/anomaly-rules", headers=h1)
    assert r.status_code == 403


async def test_update_and_delete_rule(
    client, tenant_factory, user_factory, auth_headers_factory
):
    tenant = await tenant_factory(name="REST UpdDel")
    u = await user_factory(tenant, email="updel@example.com")
    h = await auth_headers_factory(u)

    # Create
    r = await client.post(
        f"/api/orgs/{tenant.id}/anomaly-rules",
        json={
            "name": "x",
            "rule_type": RULE_ERROR_RATE,
            "threshold": 5.0,
            "window_seconds": 60,
        },
        headers=h,
    )
    assert r.status_code == 201
    rule_id = r.json()["id"]

    # Update
    r = await client.put(
        f"/api/orgs/{tenant.id}/anomaly-rules/{rule_id}",
        json={"threshold": 12.5, "enabled": False},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["threshold"] == 12.5
    assert r.json()["enabled"] is False

    # Delete
    r = await client.delete(
        f"/api/orgs/{tenant.id}/anomaly-rules/{rule_id}", headers=h
    )
    assert r.status_code == 204

    # Confirm gone
    r = await client.get(
        f"/api/orgs/{tenant.id}/anomaly-rules/{rule_id}", headers=h
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# REST: events + ack + on-demand eval
# ---------------------------------------------------------------------------


async def test_ack_anomaly_event(
    client, tenant_factory, user_factory, auth_headers_factory
):
    tenant = await tenant_factory(name="REST Ack")
    u = await user_factory(tenant, email="ack@example.com")
    h = await auth_headers_factory(u)

    # Create a rule + a finding manually
    rule = await _make_rule(tenant, rule_type=RULE_ERROR_RATE, threshold=10.0)
    await _seed_traces(
        tenant.id,
        [100] * 10,
        ["ok"] * 5 + ["error"] * 5,
    )
    async with AsyncSessionLocal() as session:
        findings = await evaluate_org(session, tenant.id)
        assert len(findings) == 1
        event = findings[0].to_event()
        session.add(event)
        await session.commit()
        await session.refresh(event)
        event_id = event.id

    r = await client.post(
        f"/api/orgs/{tenant.id}/anomaly-events/{event_id}/ack",
        json={"acknowledged_by": "ada@example.com"},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["acknowledged"] is True
    assert body["acknowledged_by"] == "ada@example.com"


async def test_on_demand_evaluate_persists_event(
    client, tenant_factory, user_factory, auth_headers_factory
):
    tenant = await tenant_factory(name="REST Eval")
    u = await user_factory(tenant, email="eval@example.com")
    h = await auth_headers_factory(u)
    rule = await _make_rule(tenant, rule_type=RULE_ERROR_RATE, threshold=10.0)
    await _seed_traces(
        tenant.id,
        [100] * 10,
        ["ok"] * 5 + ["error"] * 5,
    )

    r = await client.post(
        f"/api/orgs/{tenant.id}/anomaly-rules/{rule.id}/evaluate",
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rule_id"] == str(rule.id)
    assert body["severity"] in {"low", "medium", "high"}

    # Verify the event was persisted
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AnomalyEvent).where(AnomalyEvent.rule_id == rule.id)
        )
        events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].severity in {"low", "medium", "high"}


async def test_on_demand_evaluate_no_fire_returns_null(
    client, tenant_factory, user_factory, auth_headers_factory
):
    tenant = await tenant_factory(name="REST NoFire")
    u = await user_factory(tenant, email="nofire@example.com")
    h = await auth_headers_factory(u)
    rule = await _make_rule(tenant, rule_type=RULE_ERROR_RATE, threshold=99.0)
    # No errors -> below threshold

    r = await client.post(
        f"/api/orgs/{tenant.id}/anomaly-rules/{rule.id}/evaluate",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json() is None


async def test_evaluate_all_returns_summary(
    client, tenant_factory, user_factory, auth_headers_factory
):
    tenant = await tenant_factory(name="REST AllEval")
    u = await user_factory(tenant, email="alleval@example.com")
    h = await auth_headers_factory(u)
    await _make_rule(tenant, rule_type=RULE_ERROR_RATE, threshold=10.0, name="err")
    await _make_rule(tenant, rule_type=RULE_LATENCY_P95, threshold=500, name="lat")
    await _seed_traces(
        tenant.id,
        [1000] * 10,
        ["ok"] * 5 + ["error"] * 5,
    )

    r = await client.post(
        f"/api/orgs/{tenant.id}/anomaly-evaluate", headers=h
    )
    assert r.status_code == 200
    body = r.json()
    assert body["evaluated"] == 2
    assert body["fired"] == 2
    assert len(body["events"]) == 2
