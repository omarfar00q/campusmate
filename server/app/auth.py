"""Authentication and session identity resolution for CampusMate.

Implements Non-Negotiable Principle 4:
Identity comes strictly from the authenticated session (bearer token -> student).
NO tool accepts a student_id or group argument.
Tools query only data for the currently authenticated student.
"""

from __future__ import annotations

import contextvars
from typing import Optional
from sqlalchemy.orm import Session

from campusmate.server.app.models import AuthToken, Student

# Context variable holding the currently authenticated Student for the active request/session
_current_student_var: contextvars.ContextVar[Optional[Student]] = contextvars.ContextVar(
    "current_student", default=None
)
_current_token_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_token", default=None
)


class AuthenticationError(Exception):
    """Raised when authentication fails or token is missing/invalid."""
    pass


def resolve_student_from_token(token: str, session: Session) -> Student:
    """Resolve a bearer token to an active Student record.

    Raises AuthenticationError if the token is empty, invalid, or inactive.
    """
    if not token or not token.strip():
        raise AuthenticationError("Authorization bearer token is missing or empty.")

    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    auth_token = session.query(AuthToken).filter_by(token=clean_token, is_active=True).first()
    if not auth_token or not auth_token.student:
        raise AuthenticationError(f"Invalid or expired authorization token: '{clean_token[:10]}...'")

    return auth_token.student


def set_current_session(student: Student, token: str | None = None) -> None:
    """Set the authenticated student in the current context."""
    _current_student_var.set(student)
    if token:
        _current_token_var.set(token)


def clear_current_session() -> None:
    """Clear the authenticated session from the current context."""
    _current_student_var.set(None)
    _current_token_var.set(None)


def get_current_student() -> Student:
    """Get the student resolved for the current authenticated context.

    Raises AuthenticationError if no session is active.
    """
    student = _current_student_var.get()
    if student is None:
        raise AuthenticationError("No authenticated student session found in context.")
    return student


def get_current_token() -> str | None:
    """Get the current bearer token from context."""
    return _current_token_var.get()
