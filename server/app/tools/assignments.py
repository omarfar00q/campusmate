"""Assignments tool for CampusMate MCP Server.

Implements get_assignments(status, from_date, to_date):
- Queries assignments strictly for the authenticated student
- Calculates hours remaining against current clock (honouring frozen clock)
- Generates natural spoken speech summary
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from campusmate.server.app import clock
from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import Assignment


class AssignmentsInput(BaseModel):
    status: str = Field(
        default="pending",
        description="Filter assignments by status: 'pending', 'submitted', 'overdue', or 'all'. Default is 'pending'.",
    )
    from_date: Optional[str] = Field(
        default=None,
        description="Optional filter for assignments due on or after this date (YYYY-MM-DD).",
    )
    to_date: Optional[str] = Field(
        default=None,
        description="Optional filter for assignments due on or before this date (YYYY-MM-DD).",
    )


def execute_get_assignments(
    status: str = "pending",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve assignments for the authenticated student."""
    # 1. Resolve authenticated student from context
    try:
        student = get_current_student()
    except AuthenticationError:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "assignments": [],
            "speech_summary": "I couldn't retrieve your assignments because your session is not authenticated.",
        }

    valid_statuses = {"pending", "submitted", "overdue", "all"}
    clean_status = (status or "pending").lower().strip()
    if clean_status not in valid_statuses:
        return {
            "error": f"Invalid status '{clean_status}'. Must be one of: {', '.join(sorted(valid_statuses))}.",
            "is_error": True,
            "assignments": [],
            "speech_summary": f"'{clean_status}' is not a valid assignment status. Please use pending, submitted, overdue, or all.",
        }

    current_now = clock.now()

    with get_db_session() as session:
        query = session.query(Assignment).filter_by(student_id=student.id)

        # Status filter
        if clean_status != "all":
            query = query.filter(Assignment.status == clean_status)

        all_records = query.order_by(Assignment.due_at.asc()).all()

        formatted: List[Dict[str, Any]] = []
        for record in all_records:
            # Parse due_at datetime
            try:
                due_dt = datetime.fromisoformat(record.due_at)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=current_now.tzinfo)
            except Exception:
                due_dt = current_now

            # Optional date range filtering
            due_date_str = due_dt.strftime("%Y-%m-%d")
            if from_date and due_date_str < from_date.strip():
                continue
            if to_date and due_date_str > to_date.strip():
                continue

            time_diff = due_dt - current_now
            total_seconds = time_diff.total_seconds()
            hours_remaining = max(0.0, round(total_seconds / 3600.0, 1))
            is_overdue = total_seconds < 0 and record.status != "submitted"

            formatted.append({
                "id": record.id,
                "title": record.title,
                "subject": record.subject,
                "due_at": record.due_at,
                "status": "overdue" if is_overdue else record.status,
                "estimated_effort_minutes": record.estimated_effort_minutes,
                "hours_remaining": hours_remaining,
                "is_overdue": is_overdue,
            })

    # Generate natural speech summary
    count = len(formatted)
    if count == 0:
        speech = f"You have no {clean_status} assignments." if clean_status != "all" else "You have no assignments."
    elif count == 1:
        item = formatted[0]
        urgency = "which is overdue" if item["is_overdue"] else f"due in {item['hours_remaining']} hours"
        speech = f"You have 1 assignment: {item['title']} for {item['subject']}, {urgency}."
    else:
        overdue_cnt = sum(1 for a in formatted if a["is_overdue"])
        first = formatted[0]
        if overdue_cnt > 0:
            speech = (
                f"You have {count} assignments, including {overdue_cnt} overdue. "
                f"The earliest is {first['title']} for {first['subject']}."
            )
        else:
            speech = (
                f"You have {count} {clean_status} assignments. "
                f"The next due is {first['title']} for {first['subject']} in {first['hours_remaining']} hours."
            )

    return {
        "student_name": student.name,
        "filter_status": clean_status,
        "assignment_count": count,
        "assignments": formatted,
        "speech_summary": speech,
        "is_error": False,
    }
