"""Mute window helpers.

A source can be configured with one or more mute windows via its
``alert_config['mute_windows']`` JSON column. Each window looks like:

    {
        "days": ["saturday", "sunday"],   # day-of-week list
        "start_hour": 0,                  # 0-23, in ``timezone``
        "end_hour": 8,                    # exclusive; if < start_hour, wraps midnight
        "timezone": "UTC"
    }

If the current local time (in the window's timezone) falls inside any
window, the source is considered muted and alerts are suppressed.

This module deliberately uses only the stdlib ``zoneinfo`` module so it
has no extra dependencies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Day names accepted in mute_windows[].days. Matched case-insensitively.
_VALID_DAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


def _safe_zoneinfo(tz_name: str | None) -> ZoneInfo:
    """Return a ZoneInfo for the given name, falling back to UTC."""
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _window_active(window: dict[str, Any], now_utc: datetime | None = None) -> bool:
    """Return True if *now* falls inside the given mute window.

    Handles overnight windows where ``start_hour > end_hour`` (e.g.
    22:00-06:00) by checking the "either side of midnight" case.
    """
    if not isinstance(window, dict):
        return False

    days = window.get("days") or []
    if not isinstance(days, list) or not days:
        return False

    # Normalize day names; unknown names are silently dropped.
    normalized: set[str] = set()
    for d in days:
        if isinstance(d, str) and d.lower() in _VALID_DAYS:
            normalized.add(d.lower())
    if not normalized:
        return False

    tz = _safe_zoneinfo(window.get("timezone"))
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    local_now = now_utc.astimezone(tz)
    day_name = local_now.strftime("%A").lower()
    if day_name not in normalized:
        return False

    try:
        start_hour = int(window.get("start_hour", 0))
        end_hour = int(window.get("end_hour", 0))
    except (TypeError, ValueError):
        return False
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        return False

    current_hour = local_now.hour
    if start_hour == end_hour:
        # A zero-width window is treated as "always muted" within the
        # selected days. Avoids accidentally muting with bad config.
        return True
    if start_hour < end_hour:
        return start_hour <= current_hour < end_hour
    # Overnight wrap: 22:00-06:00 means current_hour >= 22 OR < 6
    return current_hour >= start_hour or current_hour < end_hour


def is_muted(
    source: Any | None,
    now_utc: datetime | None = None,
) -> bool:
    """Return True if *source* is currently inside any mute window.

    Accepts any object (or ``None``) that has an ``alert_config``
    attribute — typically a SQLAlchemy ``WebhookSource``. Returns False
    when the source has no mute windows configured.
    """
    if source is None:
        return False
    alert_config = getattr(source, "alert_config", None) or {}
    if not isinstance(alert_config, dict):
        return False
    windows = alert_config.get("mute_windows") or []
    if not isinstance(windows, list):
        return False
    return any(_window_active(w, now_utc=now_utc) for w in windows)


def list_active_windows(
    source: Any | None,
    now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return the subset of mute windows currently active (debug helper)."""
    if source is None:
        return []
    alert_config = getattr(source, "alert_config", None) or {}
    windows = alert_config.get("mute_windows") or []
    if not isinstance(windows, list):
        return []
    return [w for w in windows if _window_active(w, now_utc=now_utc)]


def validate_mute_windows(windows: Iterable[Any]) -> list[dict[str, Any]]:
    """Return the cleaned list of mute windows, dropping malformed entries.

    Used by the API when persisting user input so we never store invalid
    configuration.
    """
    cleaned: list[dict[str, Any]] = []
    for w in windows or []:
        if not isinstance(w, dict):
            continue
        days = w.get("days") or []
        if not isinstance(days, list) or not days:
            continue
        valid_days = [d for d in days if isinstance(d, str) and d.lower() in _VALID_DAYS]
        if not valid_days:
            continue
        try:
            start_hour = int(w.get("start_hour", 0))
            end_hour = int(w.get("end_hour", 0))
        except (TypeError, ValueError):
            continue
        if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
            continue
        tz = w.get("timezone") or "UTC"
        if not isinstance(tz, str):
            tz = "UTC"
        cleaned.append(
            {
                "days": [d.lower() for d in valid_days],
                "start_hour": start_hour,
                "end_hour": end_hour,
                "timezone": tz,
            }
        )
    return cleaned
