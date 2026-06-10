"""Sprint 2: Pydantic schema validation tests.

The schemas in ``app.schemas.observability`` carry the contract
between the WebSocket clients / REST callers and the rest of the
backend. A regression here (e.g. a loosened status validator)
would let bad data into the database, so we lock the contract
down with explicit tests for every validator and edge case.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.observability import (
    AnomalyEventAck,
    AnomalyRuleCreate,
    AnomalyRuleUpdate,
    TraceIngest,
)


# ---------------------------------------------------------------------------
# TraceIngest
# ---------------------------------------------------------------------------


class TestTraceIngest:
    def test_minimal_payload_passes(self):
        payload = TraceIngest(
            trace_id="abc",
            name="llm.completion",
            started_at=datetime.now(timezone.utc),
        )
        assert payload.status == "ok"  # default
        assert payload.attributes is None
        assert payload.workflow_id is None

    def test_status_is_normalised_to_lowercase(self):
        payload = TraceIngest(
            trace_id="abc",
            name="thing",
            started_at=datetime.now(timezone.utc),
            status="ERROR",
        )
        assert payload.status == "error"

    @pytest.mark.parametrize("status", ["ok", "error", "running", "timeout", "cancelled"])
    def test_all_valid_statuses_accepted(self, status):
        TraceIngest(
            trace_id="abc",
            name="thing",
            started_at=datetime.now(timezone.utc),
            status=status,
        )

    @pytest.mark.parametrize("status", ["EXPLODED", "nope", "200"])
    def test_invalid_status_rejected(self, status):
        with pytest.raises(ValidationError):
            TraceIngest(
                trace_id="abc",
                name="thing",
                started_at=datetime.now(timezone.utc),
                status=status,
            )

    def test_trace_id_length_bounds(self):
        with pytest.raises(ValidationError):
            TraceIngest(
                trace_id="",
                name="thing",
                started_at=datetime.now(timezone.utc),
            )
        with pytest.raises(ValidationError):
            TraceIngest(
                trace_id="a" * 129,
                name="thing",
                started_at=datetime.now(timezone.utc),
            )

    def test_name_length_bounds(self):
        with pytest.raises(ValidationError):
            TraceIngest(
                trace_id="abc",
                name="",
                started_at=datetime.now(timezone.utc),
            )
        with pytest.raises(ValidationError):
            TraceIngest(
                trace_id="abc",
                name="n" * 256,
                started_at=datetime.now(timezone.utc),
            )

    def test_duration_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            TraceIngest(
                trace_id="abc",
                name="thing",
                started_at=datetime.now(timezone.utc),
                duration_ms=-1,
            )

    def test_full_payload_roundtrip(self):
        now = datetime.now(timezone.utc)
        payload = TraceIngest(
            trace_id="trace-1",
            workflow_id="wf-1",
            name="llm.completion",
            source="openai",
            status="ok",
            started_at=now,
            ended_at=now + timedelta(seconds=1),
            duration_ms=1000,
            attributes={"model": "gpt-4", "tokens": 1234},
            error_message=None,
        )
        assert payload.workflow_id == "wf-1"
        assert payload.source == "openai"
        assert payload.attributes["model"] == "gpt-4"


# ---------------------------------------------------------------------------
# AnomalyRuleCreate
# ---------------------------------------------------------------------------


class TestAnomalyRuleCreate:
    def test_defaults_apply(self):
        r = AnomalyRuleCreate(
            name="rule-1",
            rule_type="latency_p95",
            threshold=500.0,
        )
        assert r.window_seconds == 300
        assert r.enabled is True
        assert r.workflow_id is None

    @pytest.mark.parametrize(
        "rule_type",
        ["latency_p95", "error_rate", "throughput_drop"],
    )
    def test_valid_rule_types_accepted(self, rule_type):
        AnomalyRuleCreate(
            name="r", rule_type=rule_type, threshold=10.0,
        )

    @pytest.mark.parametrize("rule_type", ["nope", "P99", "all"])
    def test_invalid_rule_types_rejected(self, rule_type):
        with pytest.raises(ValidationError):
            AnomalyRuleCreate(
                name="r", rule_type=rule_type, threshold=10.0,
            )

    def test_window_seconds_minimum(self):
        with pytest.raises(ValidationError):
            AnomalyRuleCreate(
                name="r", rule_type="latency_p95", threshold=1.0,
                window_seconds=5,
            )

    def test_window_seconds_maximum(self):
        with pytest.raises(ValidationError):
            AnomalyRuleCreate(
                name="r", rule_type="latency_p95", threshold=1.0,
                window_seconds=86401,
            )


# ---------------------------------------------------------------------------
# AnomalyRuleUpdate
# ---------------------------------------------------------------------------


class TestAnomalyRuleUpdate:
    def test_all_fields_optional(self):
        u = AnomalyRuleUpdate()
        dumped = u.model_dump(exclude_unset=True)
        assert dumped == {}

    def test_partial_update(self):
        u = AnomalyRuleUpdate(threshold=99.0, enabled=False)
        dumped = u.model_dump(exclude_unset=True)
        assert dumped == {"threshold": 99.0, "enabled": False}

    def test_invalid_rule_type_rejected(self):
        with pytest.raises(ValidationError):
            AnomalyRuleUpdate(rule_type="not-a-real-type")


# ---------------------------------------------------------------------------
# AnomalyEventAck
# ---------------------------------------------------------------------------


class TestAnomalyEventAck:
    def test_default_ack_has_no_actor(self):
        a = AnomalyEventAck()
        assert a.acknowledged_by is None

    def test_actor_set_explicitly(self):
        a = AnomalyEventAck(acknowledged_by="ada@example.com")
        assert a.acknowledged_by == "ada@example.com"

    def test_actor_length_bound(self):
        with pytest.raises(ValidationError):
            AnomalyEventAck(acknowledged_by="a" * 256)
