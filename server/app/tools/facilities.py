"""Campus facilities tool for CampusMate MCP Server.

Implements get_facility_info(name?, at_time?):
- Queries campus facility operating hours and locations (Library, Canteen, AI Lab)
- Evaluates open_now status dynamically against current or requested clock time
- Scoped to authenticated session
- Generates natural spoken speech summary
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from campusmate.server.app import clock
from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import CampusFacility


class FacilityInput(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description="Optional name of the facility to query (e.g., 'Library', 'Canteen', 'Innovation Lab').",
    )
    at_time: Optional[str] = Field(
        default=None,
        description="Optional time to check in HH:MM format (e.g. '14:30'). If omitted, checks against current time.",
    )


def execute_get_facility_info(
    name: Optional[str] = None,
    at_time: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve campus facility information and operating status."""
    try:
        student = get_current_student()
    except AuthenticationError:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "facilities": [],
            "speech_summary": "I couldn't retrieve facility details because your session is not authenticated.",
        }

    # Determine reference check time
    if at_time and at_time.strip():
        check_time_str = at_time.strip()
    else:
        check_time_str = clock.now().strftime("%H:%M")

    with get_db_session() as session:
        query = session.query(CampusFacility)

        clean_name = name.strip() if name else None
        if clean_name:
            query = query.filter(CampusFacility.name.ilike(f"%{clean_name}%"))

        db_records = query.all()

        formatted_facilities: List[Dict[str, Any]] = []
        for f in db_records:
            is_open = f.opening_time <= check_time_str <= f.closing_time
            formatted_facilities.append({
                "id": f.id,
                "name": f.name,
                "location": f.location,
                "opening_time": f.opening_time,
                "closing_time": f.closing_time,
                "days_open": f.days_open,
                "open_now": is_open,
                "description": f.description,
            })

    if not formatted_facilities:
        speech = f"I couldn't find any campus facility matching '{clean_name}'." if clean_name else "No campus facilities listed."
        return {
            "query_name": clean_name,
            "check_time": check_time_str,
            "facility_count": 0,
            "facilities": [],
            "speech_summary": speech,
            "is_error": False,
        }

    if len(formatted_facilities) == 1:
        item = formatted_facilities[0]
        status_phrase = f"currently open until {item['closing_time']}" if item["open_now"] else f"currently closed (hours: {item['opening_time']} to {item['closing_time']})"
        speech = f"{item['name']} is {status_phrase} located at {item['location']}."
    else:
        open_count = sum(1 for f in formatted_facilities if f["open_now"])
        speech = f"There are {len(formatted_facilities)} campus facilities, {open_count} currently open."

    return {
        "query_name": clean_name,
        "check_time": check_time_str,
        "facility_count": len(formatted_facilities),
        "facilities": formatted_facilities,
        "speech_summary": speech,
        "is_error": False,
    }
