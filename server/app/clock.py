"""Clock module for CampusMate.

Provides deterministic datetime retrieval with support for:
- Configurable IANA timezone via CAMPUSMATE_TZ (defaults to 'UTC')
- Frozen-clock override via CAMPUSMATE_NOW (ISO 8601 string) for tests & demos.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytz


def get_configured_timezone() -> ZoneInfo | datetime.tzinfo:
    """Return the configured timezone object."""
    tz_name = os.getenv("CAMPUSMATE_TZ", "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        try:
            return pytz.timezone(tz_name)
        except Exception:
            return ZoneInfo("UTC")


def now() -> datetime:
    """Return current timezone-aware datetime.

    Honours CAMPUSMATE_NOW if set for deterministic testing/demos.
    Always returns a timezone-aware ISO 8601 datetime with offset.
    """
    tz = get_configured_timezone()
    override = os.getenv("CAMPUSMATE_NOW", "").strip()
    if override:
        dt = datetime.fromisoformat(override)
        if dt.tzinfo is None:
            # Attach configured timezone if naive
            if isinstance(tz, ZoneInfo):
                dt = dt.replace(tzinfo=tz)
            else:
                dt = tz.localize(dt)  # type: ignore
        return dt

    return datetime.now(tz)


def get_current_date() -> date:
    """Return current date in the configured timezone."""
    return now().date()


def iso_now() -> str:
    """Return current timestamp as ISO 8601 string with offset."""
    return now().isoformat()
