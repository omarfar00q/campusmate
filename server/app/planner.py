"""Deterministic day planner for CampusMate.

Implements pure functions for:
1. Free interval computation with buffers (lunch, transitions)
2. Priority scoring: urgency (days to due) x effort weight, boosted for overdue items and nearby exams
3. Greedy fitting of study tasks into free slots with chunk splitting and break insertion
4. Honest capacity warnings when workload exceeds available time (fits_everything=False)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PlannerClass:
    subject: str
    start_time: str  # HH:MM
    end_time: str    # HH:MM
    room: str
    building: str
    floor: str


@dataclass
class PlannerTask:
    id: int | str
    title: str
    subject: str
    due_at: str  # ISO string or YYYY-MM-DD
    estimated_effort_minutes: int
    is_overdue: bool = False
    priority_score: float = 0.0


@dataclass
class PlannerExam:
    subject: str
    exam_datetime: str  # ISO string
    days_remaining: int


@dataclass
class ScheduledBlock:
    block_type: str  # "class" or "study" or "lunch"
    title: str
    subject: str
    start_time: str  # HH:MM
    end_time: str    # HH:MM
    duration_minutes: int
    reason: str
    room: Optional[str] = None
    building: Optional[str] = None


@dataclass
class DayPlanResult:
    date: str
    working_window: Dict[str, str]
    total_free_minutes: int
    total_task_minutes_needed: int
    fits_everything: bool
    schedule_blocks: List[Dict[str, Any]]
    study_blocks: List[Dict[str, Any]]
    unscheduled_tasks: List[Dict[str, Any]]
    warnings: List[str]
    speech_summary: str


def time_to_minutes(t_str: str) -> int:
    """Convert 'HH:MM' string to minutes from midnight."""
    parts = t_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def minutes_to_time(m: int) -> str:
    """Convert minutes from midnight to 'HH:MM' string."""
    hours = m // 60
    mins = m % 60
    return f"{hours:02d}:{mins:02d}"


def calculate_priority_score(
    task: PlannerTask,
    current_date: date,
    nearby_exam_subjects: set[str],
) -> float:
    """Deterministic priority score calculation.

    Higher score = higher priority (scheduled first).
    - Overdue items receive immediate +1000 base boost.
    - Tasks due within 24-48 hours receive urgency boost based on remaining days.
    - Tasks matching subjects with upcoming exams receive +200 exam boost.
    - Shorter effort tasks get a slight edge for quick turnaround.
    """
    score = 0.0

    # 1. Overdue boost
    if task.is_overdue:
        score += 1000.0

    # 2. Urgency calculation
    try:
        due_date = datetime.fromisoformat(task.due_at.replace("Z", "+00:00")).date()
        days_until_due = (due_date - current_date).days
    except Exception:
        days_until_due = 3

    if days_until_due <= 0:
        score += 500.0
    elif days_until_due == 1:
        score += 300.0
    elif days_until_due == 2:
        score += 150.0
    elif days_until_due <= 5:
        score += 50.0

    # 3. Exam proximity boost
    if task.subject in nearby_exam_subjects:
        score += 200.0

    # 4. Effort factor (favors focused chunks, slight inverse weight)
    effort_factor = max(1.0, 180.0 - task.estimated_effort_minutes) * 0.1
    score += effort_factor

    return round(score, 2)


def compute_available_free_slots_with_buffers(
    classes: List[PlannerClass],
    window_start: int,
    window_end: int,
    lunch_window: Tuple[int, int] = (12 * 60, 13 * 60 + 30),  # 12:00 to 13:30
    lunch_duration: int = 30,
) -> Tuple[List[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """Calculate free intervals, reserving a 30m lunch buffer if time permits.

    Returns:
    - List of (start_minutes, end_minutes) for free study slots.
    - Tuple of (start_minutes, end_minutes) for scheduled lunch, or None.
    """
    # 1. Collect busy class intervals
    busy_spans: List[Tuple[int, int]] = []
    for c in sorted(classes, key=lambda x: time_to_minutes(x.start_time)):
        busy_spans.append((time_to_minutes(c.start_time), time_to_minutes(c.end_time)))

    # Merge touching/overlapping class spans
    merged_busy: List[Tuple[int, int]] = []
    for b_start, b_end in sorted(busy_spans):
        if not merged_busy:
            merged_busy.append((b_start, b_end))
        else:
            prev_s, prev_e = merged_busy[-1]
            if b_start <= prev_e:
                merged_busy[-1] = (prev_s, max(prev_e, b_end))
            else:
                merged_busy.append((b_start, b_end))

    # 2. Compute initial raw free gaps
    raw_gaps: List[Tuple[int, int]] = []
    cursor = window_start
    for b_start, b_end in merged_busy:
        if b_start > cursor:
            raw_gaps.append((cursor, b_start))
        cursor = max(cursor, b_end)
    if cursor < window_end:
        raw_gaps.append((cursor, window_end))

    # 3. Reserve lunch buffer within lunch window (12:00 - 13:30) if a gap overlaps
    scheduled_lunch: Optional[Tuple[int, int]] = None
    final_study_slots: List[Tuple[int, int]] = []

    l_start_win, l_end_win = lunch_window
    lunch_allocated = False

    for gap_start, gap_end in raw_gaps:
        # Check if lunch can be placed in this gap
        if not lunch_allocated and gap_start < l_end_win and gap_end > l_start_win:
            # Overlap with lunch window
            overlap_start = max(gap_start, l_start_win)
            overlap_end = min(gap_end, l_end_win)
            if overlap_end - overlap_start >= lunch_duration:
                # Place lunch at overlap_start
                l_s = overlap_start
                l_e = overlap_start + lunch_duration
                scheduled_lunch = (l_s, l_e)
                lunch_allocated = True

                # Split gap into before-lunch and after-lunch
                if l_s > gap_start:
                    final_study_slots.append((gap_start, l_s))
                if gap_end > l_e:
                    final_study_slots.append((l_e, gap_end))
                continue

        final_study_slots.append((gap_start, gap_end))

    return final_study_slots, scheduled_lunch


def plan_day_schedule(
    plan_date: date,
    classes: List[PlannerClass],
    tasks: List[PlannerTask],
    exams: List[PlannerExam],
    day_start_str: str = "08:00",
    day_end_str: str = "18:30",
    min_study_chunk: int = 30,
    max_study_chunk: int = 90,
) -> DayPlanResult:
    """Pure, deterministic greedy planner.

    Fits priority-ranked study tasks into free slots around classes and lunch.
    Splits tasks longer than max_study_chunk or available slot.
    Generates honest warnings when tasks cannot fit into available time.
    """
    w_start = time_to_minutes(day_start_str)
    w_end = time_to_minutes(day_end_str)

    # 1. Identify nearby exam subjects (within 7 days)
    nearby_exam_subjects = {
        e.subject for e in exams if 0 <= e.days_remaining <= 7
    }

    # 2. Score and sort tasks
    for t in tasks:
        t.priority_score = calculate_priority_score(t, plan_date, nearby_exam_subjects)

    # Highest score first; if tie, earliest due_at; then shorter effort
    sorted_tasks = sorted(
        tasks,
        key=lambda x: (-x.priority_score, x.due_at, x.estimated_effort_minutes)
    )

    total_task_minutes_needed = sum(t.estimated_effort_minutes for t in sorted_tasks)

    # 3. Calculate available study slots and lunch buffer
    study_slots, lunch_span = compute_available_free_slots_with_buffers(
        classes=classes,
        window_start=w_start,
        window_end=w_end,
    )

    total_free_minutes = sum(end - start for start, end in study_slots)

    # 4. Greedy fit
    scheduled_study_blocks: List[ScheduledBlock] = []
    unscheduled_tasks: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # Queue of remaining work: list of [task, remaining_minutes, part_index]
    work_queue: List[List[Any]] = [
        [t, t.estimated_effort_minutes, 1] for t in sorted_tasks
    ]

    for slot_start, slot_end in study_slots:
        current_time = slot_start

        while current_time < slot_end and work_queue:
            available_time = slot_end - current_time
            if available_time < min_study_chunk:
                break

            current_work = work_queue[0]
            task: PlannerTask = current_work[0]
            rem_mins: int = current_work[1]
            part_idx: int = current_work[2]

            # Determine chunk size to schedule
            chunk_size = min(rem_mins, available_time, max_study_chunk)

            block_title = task.title if rem_mins <= chunk_size and part_idx == 1 else f"{task.title} (Part {part_idx})"
            reason = "Overdue assignment" if task.is_overdue else (
                f"Upcoming exam preparation for {task.subject}" if task.subject in nearby_exam_subjects else (
                    f"Due in near term for {task.subject}"
                )
            )

            b_start = current_time
            b_end = current_time + chunk_size

            scheduled_study_blocks.append(
                ScheduledBlock(
                    block_type="study",
                    title=block_title,
                    subject=task.subject,
                    start_time=minutes_to_time(b_start),
                    end_time=minutes_to_time(b_end),
                    duration_minutes=chunk_size,
                    reason=reason,
                )
            )

            current_time = b_end
            rem_mins -= chunk_size

            if rem_mins <= 0:
                work_queue.pop(0)
            else:
                current_work[1] = rem_mins
                current_work[2] = part_idx + 1
                # Small 5m break if time remains in slot
                if current_time + 5 + min_study_chunk <= slot_end:
                    current_time += 5

    # Any remaining tasks in work_queue are unscheduled or partially unscheduled
    for work in work_queue:
        t: PlannerTask = work[0]
        rem_m: int = work[1]
        part: int = work[2]
        unscheduled_tasks.append({
            "task_id": t.id,
            "title": t.title,
            "subject": t.subject,
            "unfitted_minutes": rem_m,
            "total_estimated_minutes": t.estimated_effort_minutes,
            "is_overdue": t.is_overdue,
            "partially_scheduled": part > 1,
        })

    fits_everything = len(unscheduled_tasks) == 0

    if not fits_everything:
        needed_extra = sum(u["unfitted_minutes"] for u in unscheduled_tasks)
        extra_h = needed_extra // 60
        extra_m = needed_extra % 60
        extra_str = f"{extra_h}h {extra_m}m" if extra_m > 0 else f"{extra_h}h"
        free_h = total_free_minutes // 60
        free_m = total_free_minutes % 60
        free_str = f"{free_h}h {free_m}m" if free_m > 0 else f"{free_h}h"
        warnings.append(
            f"Insufficient free time: tasks required {total_task_minutes_needed // 60}h {total_task_minutes_needed % 60}m, "
            f"but only {free_str} free. Unscheduled deficit: {extra_str}."
        )

    # 5. Assemble unified timeline (classes, study blocks, lunch)
    all_blocks: List[ScheduledBlock] = []

    # Add classes
    for c in classes:
        dur = time_to_minutes(c.end_time) - time_to_minutes(c.start_time)
        all_blocks.append(
            ScheduledBlock(
                block_type="class",
                title=f"Class: {c.subject}",
                subject=c.subject,
                start_time=c.start_time,
                end_time=c.end_time,
                duration_minutes=dur,
                reason="Scheduled lecture",
                room=c.room,
                building=c.building,
            )
        )

    # Add lunch if scheduled
    if lunch_span:
        l_s, l_e = lunch_span
        all_blocks.append(
            ScheduledBlock(
                block_type="lunch",
                title="Lunch & Rest Break",
                subject="Campus Canteen / Break",
                start_time=minutes_to_time(l_s),
                end_time=minutes_to_time(l_e),
                duration_minutes=l_e - l_s,
                reason="Midday meal and buffer",
            )
        )

    # Add study blocks
    all_blocks.extend(scheduled_study_blocks)

    # Sort all blocks by start time
    all_blocks.sort(key=lambda b: time_to_minutes(b.start_time))

    formatted_all_blocks = [
        {
            "type": b.block_type,
            "title": b.title,
            "subject": b.subject,
            "start": b.start_time,
            "end": b.end_time,
            "duration_minutes": b.duration_minutes,
            "reason": b.reason,
            "room": b.room,
            "building": b.building,
        }
        for b in all_blocks
    ]

    formatted_study_blocks = [
        {
            "title": b.title,
            "subject": b.subject,
            "start": b.start_time,
            "end": b.end_time,
            "duration_minutes": b.duration_minutes,
            "reason": b.reason,
        }
        for b in scheduled_study_blocks
    ]

    # Generate spoken speech summary
    class_cnt = len(classes)
    study_cnt = len(scheduled_study_blocks)
    if class_cnt > 0 and study_cnt > 0:
        first_item = all_blocks[0]
        speech = (
            f"You have {class_cnt} classes and {study_cnt} study sessions planned today, "
            f"starting with {first_item.title} at {first_item.start_time}."
        )
    elif class_cnt > 0:
        speech = f"You have {class_cnt} classes scheduled today, starting at {classes[0].start_time}."
    elif study_cnt > 0:
        speech = f"You have no classes today. I have organized {study_cnt} study blocks for your assignments."
    else:
        speech = "Your schedule is clear today with no classes or pending assignments."

    if not fits_everything:
        speech += f" Note: You have {len(unscheduled_tasks)} task that couldn't fit into available free time."

    return DayPlanResult(
        date=plan_date.isoformat(),
        working_window={"start": day_start_str, "end": day_end_str},
        total_free_minutes=total_free_minutes,
        total_task_minutes_needed=total_task_minutes_needed,
        fits_everything=fits_everything,
        schedule_blocks=formatted_all_blocks,
        study_blocks=formatted_study_blocks,
        unscheduled_tasks=unscheduled_tasks,
        warnings=warnings,
        speech_summary=speech,
    )
