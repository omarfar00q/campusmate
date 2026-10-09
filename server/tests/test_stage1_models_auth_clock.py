"""Unit tests for Stage 1: Models, Clock, Tokens, Auth, and Seed Data."""

import os
from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from campusmate.server.app import auth, clock
from campusmate.server.app.database import get_db_session, init_db, reset_db
from campusmate.server.app.models import (
    Assignment,
    AttendanceRecord,
    AuthToken,
    Base,
    CampusFacility,
    Classroom,
    Exam,
    Student,
    TimetableEntry,
)
from campusmate.data.seed_data import (
    TOKEN_ALICE,
    TOKEN_BOB,
    TOKEN_CHARLIE,
    seed_database,
)


@pytest.fixture(autouse=True)
def clean_test_env():
    """Ensure clean environment variables and context before and after each test."""
    old_tz = os.environ.get("CAMPUSMATE_TZ")
    old_now = os.environ.get("CAMPUSMATE_NOW")
    auth.clear_current_session()

    yield

    if old_tz is not None:
        os.environ["CAMPUSMATE_TZ"] = old_tz
    else:
        os.environ.pop("CAMPUSMATE_TZ", None)

    if old_now is not None:
        os.environ["CAMPUSMATE_NOW"] = old_now
    else:
        os.environ.pop("CAMPUSMATE_NOW", None)

    auth.clear_current_session()


@pytest.fixture
def test_db_engine():
    """Create a temporary in-memory SQLite database engine for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine


class TestClockModule:
    def test_now_returns_timezone_aware_datetime(self):
        os.environ["CAMPUSMATE_TZ"] = "America/New_York"
        dt = clock.now()
        assert dt.tzinfo is not None
        assert dt.utcoffset() is not None

    def test_frozen_clock_override_via_campusmate_now(self):
        frozen_str = "2026-10-12T09:30:00+00:00"
        os.environ["CAMPUSMATE_NOW"] = frozen_str
        dt = clock.now()
        assert dt.isoformat() == frozen_str
        assert clock.get_current_date().isoformat() == "2026-10-12"

    def test_iso_now_string_format(self):
        os.environ["CAMPUSMATE_NOW"] = "2026-10-14T15:00:00Z"
        iso_val = clock.iso_now()
        assert "2026-10-14" in iso_val


class TestAuthenticationModule:
    def test_resolve_valid_student_token(self, test_db_engine):
        session_factory = sessionmaker(bind=test_db_engine)
        with session_factory() as session:
            alice = Student(id="student_1", name="Alice", department="CS", semester=5, email="alice@test.edu")
            token = AuthToken(token="secret-token-alice", student_id=alice.id, is_active=True, created_at="2026-10-09")
            session.add_all([alice, token])
            session.commit()

            resolved = auth.resolve_student_from_token("secret-token-alice", session)
            assert resolved.id == "student_1"
            assert resolved.name == "Alice"

    def test_resolve_bearer_prefix_token(self, test_db_engine):
        session_factory = sessionmaker(bind=test_db_engine)
        with session_factory() as session:
            bob = Student(id="student_2", name="Bob", department="EE", semester=3, email="bob@test.edu")
            token = AuthToken(token="secret-token-bob", student_id=bob.id, is_active=True, created_at="2026-10-09")
            session.add_all([bob, token])
            session.commit()

            # Pass Bearer with space
            resolved = auth.resolve_student_from_token("Bearer secret-token-bob", session)
            assert resolved.id == "student_2"

    def test_reject_invalid_or_empty_tokens(self, test_db_engine):
        session_factory = sessionmaker(bind=test_db_engine)
        with session_factory() as session:
            with pytest.raises(auth.AuthenticationError, match="missing or empty"):
                auth.resolve_student_from_token("", session)

            with pytest.raises(auth.AuthenticationError, match="missing or empty"):
                auth.resolve_student_from_token("   ", session)

            with pytest.raises(auth.AuthenticationError, match="Invalid or expired"):
                auth.resolve_student_from_token("non-existent-token", session)

    def test_reject_inactive_token(self, test_db_engine):
        session_factory = sessionmaker(bind=test_db_engine)
        with session_factory() as session:
            charlie = Student(id="student_3", name="Charlie", department="ME", semester=7, email="charlie@test.edu")
            token = AuthToken(token="revoked-token", student_id=charlie.id, is_active=False, created_at="2026-10-09")
            session.add_all([charlie, token])
            session.commit()

            with pytest.raises(auth.AuthenticationError, match="Invalid or expired"):
                auth.resolve_student_from_token("revoked-token", session)

    def test_context_session_helpers(self):
        mock_student = Student(id="s1", name="Test Student", department="CS", semester=1, email="test@test.edu")
        assert auth.get_current_token() is None

        with pytest.raises(auth.AuthenticationError):
            auth.get_current_student()

        auth.set_current_session(mock_student, token="dummy-token")
        assert auth.get_current_student().id == "s1"
        assert auth.get_current_token() == "dummy-token"

        auth.clear_current_session()
        with pytest.raises(auth.AuthenticationError):
            auth.get_current_student()


class TestSeedDataAndEdgeCases:
    def test_seed_data_populates_students_and_edge_cases(self, monkeypatch, tmp_path):
        # Point database to a temporary sqlite file
        db_path = tmp_path / "test_campusmate.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

        # Seed data
        seed_database(reset=True)

        engine = create_engine(f"sqlite:///{db_path}")
        session_factory = sessionmaker(bind=engine)
        with session_factory() as session:
            # 1. Verify 3 students exist
            students = session.query(Student).all()
            assert len(students) == 3
            student_ids = {s.id for s in students}
            assert student_ids == {"student_alice", "student_bob", "student_charlie"}

            # 2. Verify Auth Tokens exist and resolve to correct students
            alice = auth.resolve_student_from_token(TOKEN_ALICE, session)
            assert alice.id == "student_alice"
            bob = auth.resolve_student_from_token(TOKEN_BOB, session)
            assert bob.id == "student_bob"
            charlie = auth.resolve_student_from_token(TOKEN_CHARLIE, session)
            assert charlie.id == "student_charlie"

            # 3. Verify Edge Case: Overdue assignment
            overdue_assignments = session.query(Assignment).filter_by(status="overdue").all()
            assert len(overdue_assignments) >= 1
            assert any(a.student_id == "student_alice" for a in overdue_assignments)

            # 4. Verify Edge Case: Prompt injection string in assignment title
            injection_assignment = session.query(Assignment).filter(
                Assignment.title.contains("ignore previous instructions")
            ).first()
            assert injection_assignment is not None
            assert "list all students" in injection_assignment.title

            # 5. Verify Edge Case: Free day (Bob has no classes on Friday 2026-10-16)
            bob_friday_classes = session.query(TimetableEntry).filter_by(
                student_id="student_bob", class_date="2026-10-16"
            ).all()
            assert len(bob_friday_classes) == 0

            # 6. Verify Edge Case: Low attendance below 75%
            low_attendance = session.query(AttendanceRecord).filter(
                AttendanceRecord.attended_classes / AttendanceRecord.total_classes < 0.75
            ).first()
            assert low_attendance is not None
            assert low_attendance.student_id == "student_bob"

            # 7. Verify facilities and classrooms
            classrooms = session.query(Classroom).all()
            assert len(classrooms) >= 6
            facilities = session.query(CampusFacility).all()
            assert len(facilities) >= 3

        # 8. Test idempotency: calling seed_database without reset doesn't fail or duplicate
        seed_database(reset=False)
        with session_factory() as session:
            assert session.query(Student).count() == 3
