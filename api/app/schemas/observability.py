"""Pydantic schemas for Sprint 2 observability features.

* ``TraceIngest`` — what clients send over the WebSocket.
* ``TraceResponse`` — what the API returns.
* ``AnomalyRuleCreate/Update/Response`` — anomaly rule CRUD.
* ``AnomalyEventResponse`` — anomaly event response + ack.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.observability import VALID_RULE_TYPES


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


class TraceIngest(BaseModel):
    """Payload accepted by the WebSocket ingestion channel.

    ``trace_id`` is a stable identifier supplied by the caller
    (e.g. an OpenTelemetry ``trace_id`` hex). ``name`` is the
    user-visible label such as ``"llm.completion"``. ``attributes``
    is a free-form JSON blob for model name, token counts, etc.

    ``spans`` (Sprint 4) is an optional ordered list of child
    spans. Each span is a dict with at minimum ``span_id`` and
    ``name``; ``parent_id`` references another span in the same
    trace (or ``None`` for root-level spans). The dashboard renders
    the spans as a DAG.
    """

    trace_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    workflow_id: Optional[str] = Field(None, max_length=128)
    source: Optional[str] = Field(None, max_length=64)
    status: str = Field("ok", max_length=16)
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = Field(None, ge=0)
    attributes: Optional[dict] = None
    error_message: Optional[str] = None
    spans: Optional[list] = Field(
        default=None,
        description=(
            "Ordered list of child spans forming the trace DAG. "
            "Each span: {span_id, parent_id?, name, status?, "
            "started_at?, ended_at?, duration_ms?, attributes?, "
            "error_message?}."
        ),
    )

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        v = v.lower()
        if v not in {"ok", "error", "running", "timeout", "cancelled"}:
            raise ValueError(f"invalid status: {v}")
        return v

    @field_validator("spans")
    @classmethod
    def _valid_spans(cls, v):
        """Validate span shape. We keep this lenient: each entry
        must be a dict, must have a non-empty ``span_id`` and
        ``name``, and ``status`` (if present) must be a known value.
        """
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("spans must be a list")
        ids: set[str] = set()
        for idx, span in enumerate(v):
            if not isinstance(span, dict):
                raise ValueError(f"spans[{idx}] must be an object")
            sid = span.get("span_id")
            name = span.get("name")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"spans[{idx}].span_id is required")
            if not isinstance(name, str) or not name:
                raise ValueError(f"spans[{idx}].name is required")
            if sid in ids:
                raise ValueError(f"spans[{idx}].span_id is duplicated: {sid}")
            ids.add(sid)
            parent = span.get("parent_id")
            if parent is not None and not isinstance(parent, str):
                raise ValueError(
                    f"spans[{idx}].parent_id must be a string or null"
                )
            status = span.get("status")
            if status is not None:
                if not isinstance(status, str):
                    raise ValueError(
                        f"spans[{idx}].status must be a string"
                    )
                status_lower = status.lower()
                if status_lower not in {
                    "ok",
                    "error",
                    "running",
                    "timeout",
                    "cancelled",
                }:
                    raise ValueError(
                        f"spans[{idx}].status invalid: {status}"
                    )
        # parent_ids should resolve to a sibling span (or be None).
        for idx, span in enumerate(v):
            parent = span.get("parent_id")
            if parent is None:
                continue
            if parent not in ids:
                raise ValueError(
                    f"spans[{idx}].parent_id references unknown span: {parent}"
                )
        return v


class TraceResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    trace_id: str
    workflow_id: Optional[str]
    name: str
    source: Optional[str]
    status: str
    started_at: datetime
    ended_at: Optional[datetime]
    duration_ms: Optional[int]
    attributes: Optional[dict]
    error_message: Optional[str]
    spans: list = []
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Anomaly rules
# ---------------------------------------------------------------------------


class AnomalyRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    rule_type: str = Field(..., max_length=32)
    threshold: float
    window_seconds: int = Field(300, ge=10, le=86400)
    workflow_id: Optional[str] = Field(None, max_length=128)
    enabled: bool = True

    @field_validator("rule_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in VALID_RULE_TYPES:
            raise ValueError(
                f"rule_type must be one of {VALID_RULE_TYPES}, got {v!r}"
            )
        return v


class AnomalyRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    rule_type: Optional[str] = Field(None, max_length=32)
    threshold: Optional[float] = None
    window_seconds: Optional[int] = Field(None, ge=10, le=86400)
    workflow_id: Optional[str] = Field(None, max_length=128)
    enabled: Optional[bool] = None

    @field_validator("rule_type")
    @classmethod
    def _valid_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in VALID_RULE_TYPES:
            raise ValueError(
                f"rule_type must be one of {VALID_RULE_TYPES}, got {v!r}"
            )
        return v


class AnomalyRuleResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    rule_type: str
    threshold: float
    window_seconds: int
    workflow_id: Optional[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Anomaly events
# ---------------------------------------------------------------------------


class AnomalyEventResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    rule_id: uuid.UUID
    detected_at: datetime
    severity: str
    message: str
    context: Optional[dict]
    acknowledged: bool
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[datetime]

    class Config:
        from_attributes = True


class AnomalyEventAck(BaseModel):
    acknowledged_by: Optional[str] = Field(None, max_length=255)


__all__ = [
    "TraceIngest",
    "TraceResponse",
    "AnomalyRuleCreate",
    "AnomalyRuleUpdate",
    "AnomalyRuleResponse",
    "AnomalyEventResponse",
    "AnomalyEventAck",
]
