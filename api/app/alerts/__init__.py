"""Sprint 1-3 alert subsystem.

Re-exports the public surface for tests and downstream code.
"""

from app.alerts.mute_windows import (
    is_muted,
    list_active_windows,
    validate_mute_windows,
)
from app.alerts.escalation import (
    find_alerts_to_escalate,
    get_escalation_config,
)
from app.alerts.slack import (
    SlackPayload,
    SlackNotifier,
    SEVERITY_COLORS,
    VALID_SEVERITIES,
    severity_color,
    format_metric_human,
    build_slack_message,
    payload_from_event,
)

__all__ = [
    # mute windows
    "is_muted",
    "list_active_windows",
    "validate_mute_windows",
    # escalation
    "find_alerts_to_escalate",
    "get_escalation_config",
    # slack
    "SlackPayload",
    "SlackNotifier",
    "SEVERITY_COLORS",
    "VALID_SEVERITIES",
    "severity_color",
    "format_metric_human",
    "build_slack_message",
    "payload_from_event",
]
