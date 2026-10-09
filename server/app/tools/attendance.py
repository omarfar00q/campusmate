"""Attendance tool for CampusMate MCP Server.

Implements get_attendance(subject?):
- Calculates percentage: (attended / total) * 100
- Calculates classes_can_still_miss to stay above configurable minimum threshold
- Computes classes_needed_to_reach_threshold if already below threshold
- Directly answers questions like "Can I skip tomorrow's class?"
- Generates natural spoken speech summary
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import AttendanceRecord


class AttendanceInput(BaseModel):
    subject: Optional[str] = Field(
        default=None,
        description="Optional subject name to check attendance for (e.g. 'Operating Systems'). If omitted, returns all subjects.",
    )


def calculate_attendance_metrics(
    attended: int,
    total: int,
    min_threshold_pct: float = 75.0,
) -> Dict[str, Any]:
    """Calculate attendance percentage and safe skip margins."""
    if total == 0:
        return {
            "percentage": 100.0,
            "classes_can_still_miss": 0,
            "classes_needed_to_reach_threshold": 0,
            "is_below_threshold": False,
            "is_on_borderline": False,
        }

    pct = round((attended / total) * 100.0, 1)
    threshold_ratio = min_threshold_pct / 100.0

    is_below = pct < min_threshold_pct
    can_miss = 0
    needed_to_recover = 0

    if not is_below:
        # Max additional missed classes while maintaining >= threshold_ratio
        # attended / (total + X) >= threshold_ratio => X <= (attended / threshold_ratio) - total
        max_miss = math.floor((attended / threshold_ratio) - total)
        can_miss = max(0, max_miss)
    else:
        # Number of consecutive attended classes needed to reach threshold
        # (attended + Y) / (total + Y) >= threshold_ratio
        # Y * (1 - threshold_ratio) >= threshold_ratio * total - attended
        deficit = (threshold_ratio * total) - attended
        needed_to_recover = math.ceil(deficit / (1.0 - threshold_ratio))

    is_borderline = not is_below and can_miss == 0

    return {
        "percentage": pct,
        "classes_can_still_miss": can_miss,
        "classes_needed_to_reach_threshold": needed_to_recover,
        "is_below_threshold": is_below,
        "is_on_borderline": is_borderline,
    }


def execute_get_attendance(subject: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve attendance records and skip headroom for authenticated student."""
    try:
        student = get_current_student()
    except AuthenticationError:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "records": [],
            "speech_summary": "I couldn't retrieve your attendance because your session is not authenticated.",
        }

    with get_db_session() as session:
        query = session.query(AttendanceRecord).filter_by(student_id=student.id)

        clean_subj = subject.strip() if subject else None
        if clean_subj:
            query = query.filter(AttendanceRecord.subject.ilike(f"%{clean_subj}%"))

        db_records = query.all()

        formatted_records: List[Dict[str, Any]] = []
        for r in db_records:
            metrics = calculate_attendance_metrics(
                attended=r.attended_classes,
                total=r.total_classes,
                min_threshold_pct=r.min_threshold_percentage,
            )
            formatted_records.append({
                "subject": r.subject,
                "attended": r.attended_classes,
                "total": r.total_classes,
                "percentage": metrics["percentage"],
                "threshold_percentage": r.min_threshold_percentage,
                "classes_can_still_miss": metrics["classes_can_still_miss"],
                "classes_needed_to_recover": metrics["classes_needed_to_reach_threshold"],
                "status": "below_threshold" if metrics["is_below_threshold"] else (
                    "borderline" if metrics["is_on_borderline"] else "safe"
                ),
            })

    if not formatted_records:
        if clean_subj:
            speech = f"I couldn't find attendance records for '{clean_subj}'."
        else:
            speech = "You have no attendance records on file."
        return {
            "student_name": student.name,
            "records": [],
            "speech_summary": speech,
            "is_error": False,
        }

    # Generate speech summary
    if len(formatted_records) == 1:
        rec = formatted_records[0]
        if rec["status"] == "below_threshold":
            speech = (
                f"Your attendance in {rec['subject']} is {rec['percentage']}%, which is below the "
                f"{rec['threshold_percentage']}% requirement. You cannot skip and need to attend the next "
                f"{rec['classes_needed_to_recover']} classes."
            )
        elif rec["status"] == "borderline":
            speech = (
                f"Your attendance in {rec['subject']} is exactly {rec['percentage']}%. "
                f"You cannot miss any more classes without falling below the {rec['threshold_percentage']}% threshold."
            )
        else:
            speech = (
                f"Your attendance in {rec['subject']} is {rec['percentage']}%. "
                f"You can still miss {rec['classes_can_still_miss']} class"
                f"{'es' if rec['classes_can_still_miss'] > 1 else ''} and stay above the {rec['threshold_percentage']}% threshold."
            )
    else:
        below_count = sum(1 for r in formatted_records if r["status"] == "below_threshold")
        borderline_count = sum(1 for r in formatted_records if r["status"] == "borderline")
        if below_count > 0:
            speech = (
                f"You have {len(formatted_records)} subjects. Warning: {below_count} subject is below the 75% threshold."
            )
        elif borderline_count > 0:
            speech = (
                f"You have {len(formatted_records)} subjects. Note: {borderline_count} subject is on the borderline 75% threshold."
            )
        else:
            speech = (
                f"Your attendance across all {len(formatted_records)} subjects is safely above the required threshold."
            )

    return {
        "student_name": student.name,
        "subject_filter": clean_subj,
        "records": formatted_records,
        "speech_summary": speech,
        "is_error": False,
    }
