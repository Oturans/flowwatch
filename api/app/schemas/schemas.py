from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import Optional


class MuteWindow(BaseModel):
    """A single time-range during which alerts are suppressed for a source."""

    days: list[str] = Field(
        ...,
        description="Day names (monday..sunday). Matched case-insensitively.",
    )
    start_hour: int = Field(0, ge=0, le=23)
    end_hour: int = Field(0, ge=0, le=23)
    timezone: str = Field("UTC", description="IANA timezone name (e.g. UTC, America/New_York)")


class EscalationRule(BaseModel):
    """Acknowledge-to-suppress escalation config."""

    enabled: bool = False
    minutes_until_escalate: int = Field(15, ge=1, le=10080)
    escalate_to: list[str] = Field(default_factory=list)


class AlertRulesUpdate(BaseModel):
    """Body for PUT /api/sources/{source_id}/alert-rules.

    Both ``mute_windows`` and ``escalation`` are optional; omitted keys
    are left untouched.
    """

    mute_windows: Optional[list[MuteWindow]] = None
    escalation: Optional[EscalationRule] = None


class WebhookSourceCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, description="Unique source identifier")
    name: str = Field(..., min_length=1, max_length=255)
    signing_secret: str = Field(..., min_length=8, description="HMAC signing secret")
    platform: str = Field(..., description="Platform: n8n, make, custom")
    alert_config: dict = Field(default_factory=dict)


class WebhookSourceResponse(BaseModel):
    id: str
    name: str
    platform: str
    alert_config: dict
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WebhookSourceUpdate(BaseModel):
    name: Optional[str] = None
    alert_config: Optional[dict] = None
    is_active: Optional[bool] = None


class EventCreate(BaseModel):
    workflow_id: str = Field(..., max_length=128)
    run_id: Optional[str] = Field(None, max_length=128)
    event_type: str = Field(..., description="Event type: started, completed, failed, retried")
    status: str = Field(..., description="Status: success, error, running, timeout")
    payload: Optional[dict] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = Field(None, ge=0)


class EventResponse(BaseModel):
    id: UUID
    source_id: str
    workflow_id: str
    run_id: Optional[str]
    event_type: str
    status: str
    payload: Optional[dict]
    error_message: Optional[str]
    duration_ms: Optional[int]
    received_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_events: int
    success_count: int
    error_count: int
    success_rate: float
    active_sources: int
    events_today: int


class AlertLogResponse(BaseModel):
    id: UUID
    source_id: str
    alert_type: str
    triggered_at: datetime
    message: Optional[str]
    status: str

    class Config:
        from_attributes = True