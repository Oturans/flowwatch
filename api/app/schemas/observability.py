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

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        v = v.lower()
        if v not in {"ok", "error", "running", "timeout", "cancelled"}:
            raise ValueError(f"invalid status: {v}")
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
