"""SQLAlchemy 2.0 ORM models for CampusMate.

Represents:
- Students & Bearer Tokens (Session Authentication)
- Timetable / Classes
- Assignments
- Exams
- Attendance
- Classrooms & Campus Facilities
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    # Relationships
    tokens: Mapped[list["AuthToken"]] = relationship("AuthToken", back_populates="student", cascade="all, delete-orphan")
    timetable_entries: Mapped[list["TimetableEntry"]] = relationship("TimetableEntry", back_populates="student", cascade="all, delete-orphan")
    assignments: Mapped[list["Assignment"]] = relationship("Assignment", back_populates="student", cascade="all, delete-orphan")
    exams: Mapped[list["Exam"]] = relationship("Exam", back_populates="student", cascade="all, delete-orphan")
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship("AttendanceRecord", back_populates="student", cascade="all, delete-orphan")


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    token: Mapped[str] = mapped_column(String(100), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(50), ForeignKey("students.id"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)

    student: Mapped["Student"] = relationship("Student", back_populates="tokens")


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(50), ForeignKey("students.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    class_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    room: Mapped[str] = mapped_column(String(50), nullable=False)
    building: Mapped[str] = mapped_column(String(100), nullable=False)
    floor: Mapped[str] = mapped_column(String(50), nullable=False)

    student: Mapped["Student"] = relationship("Student", back_populates="timetable_entries")


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(50), ForeignKey("students.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due_at: Mapped[str] = mapped_column(String(35), nullable=False, index=True)  # ISO 8601 with offset
    estimated_effort_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending, submitted, overdue

    student: Mapped["Student"] = relationship("Student", back_populates="assignments")


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(50), ForeignKey("students.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    exam_datetime: Mapped[str] = mapped_column(String(35), nullable=False, index=True)  # ISO 8601 with offset
    room: Mapped[str] = mapped_column(String(50), nullable=False)
    building: Mapped[str] = mapped_column(String(100), nullable=False)

    student: Mapped["Student"] = relationship("Student", back_populates="exams")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(50), ForeignKey("students.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    attended_classes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_classes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_threshold_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=75.0)

    student: Mapped["Student"] = relationship("Student", back_populates="attendance_records")


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    building: Mapped[str] = mapped_column(String(100), nullable=False)
    floor: Mapped[str] = mapped_column(String(50), nullable=False)
    directions: Mapped[str] = mapped_column(Text, nullable=False)


class CampusFacility(Base):
    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    opening_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    closing_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    days_open: Mapped[str] = mapped_column(String(50), nullable=False, default="Mon-Sat")
    description: Mapped[str] = mapped_column(Text, nullable=False)
