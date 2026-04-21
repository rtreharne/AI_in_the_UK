from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Count, Max
from django.utils import timezone

from .models import Sector, StudentAssignment, WorkshopRun, WorkshopSection, WorkshopSettings


@dataclass
class AssignmentResult:
    assignment: StudentAssignment
    created: bool


def enabled_sections():
    return list(WorkshopSection.objects.filter(enabled=True).order_by('order', 'id'))


def first_enabled_section() -> WorkshopSection | None:
    return WorkshopSection.objects.filter(enabled=True).order_by('order', 'id').first()


def next_enabled_section(current_section: WorkshopSection | None) -> WorkshopSection | None:
    if current_section is None:
        return first_enabled_section()

    return (
        WorkshopSection.objects.filter(enabled=True, order__gt=current_section.order)
        .order_by('order', 'id')
        .first()
    )


def previous_enabled_section(current_section: WorkshopSection | None) -> WorkshopSection | None:
    if current_section is None:
        return WorkshopSection.objects.filter(enabled=True).order_by('-order', '-id').first()

    return (
        WorkshopSection.objects.filter(enabled=True, order__lt=current_section.order)
        .order_by('-order', '-id')
        .first()
    )


def running_remaining_seconds(run: WorkshopRun) -> int:
    if run.timer_status == WorkshopRun.TIMER_RUNNING and run.end_at:
        return max(0, math.ceil((run.end_at - timezone.now()).total_seconds()))
    if run.timer_status == WorkshopRun.TIMER_PAUSED:
        return run.paused_remaining_seconds
    if run.timer_status == WorkshopRun.TIMER_READY and run.current_section:
        return run.current_section.duration_seconds
    return 0


def start_timer(run: WorkshopRun) -> None:
    if run.timer_status == WorkshopRun.TIMER_COMPLETED:
        raise ValueError('Workshop has completed. Reset to start again.')

    if run.timer_status == WorkshopRun.TIMER_RUNNING:
        return

    if run.current_section is None:
        first = first_enabled_section()
        if first is None:
            raise ValueError('No enabled sections configured.')
        run.current_section = first

    if run.timer_status == WorkshopRun.TIMER_PAUSED and run.paused_remaining_seconds > 0:
        duration = run.paused_remaining_seconds
    else:
        duration = run.current_section.duration_seconds

    run.timer_status = WorkshopRun.TIMER_RUNNING
    run.end_at = timezone.now() + timedelta(seconds=duration)
    run.paused_remaining_seconds = 0
    if run.started_at is None:
        run.started_at = timezone.now()
    run.save()


def pause_timer(run: WorkshopRun) -> None:
    if run.timer_status != WorkshopRun.TIMER_RUNNING or run.end_at is None:
        return

    remaining = max(0, math.ceil((run.end_at - timezone.now()).total_seconds()))
    run.timer_status = WorkshopRun.TIMER_PAUSED
    run.end_at = None
    run.paused_remaining_seconds = remaining
    run.save()


def move_to_next_section(run: WorkshopRun, keep_running: bool = False, reference_end_at=None) -> None:
    next_section = next_enabled_section(run.current_section)

    if next_section is None:
        run.timer_status = WorkshopRun.TIMER_COMPLETED
        run.current_section = None
        run.end_at = None
        run.paused_remaining_seconds = 0
        run.completed_at = timezone.now()
        run.save()
        return

    run.current_section = next_section
    run.paused_remaining_seconds = 0

    if keep_running:
        base = reference_end_at or timezone.now()
        run.timer_status = WorkshopRun.TIMER_RUNNING
        run.end_at = base + timedelta(seconds=next_section.duration_seconds)
    else:
        run.timer_status = WorkshopRun.TIMER_READY
        run.end_at = None

    run.save()


def _pitch_group_count(settings: WorkshopSettings) -> int:
    target = max(1, settings.target_group_size)
    predicted = max(1, math.ceil(settings.predicted_class_size / target))
    assigned_max = StudentAssignment.objects.aggregate(max_group=Max('group_number'))['max_group'] or 0
    return max(1, predicted, assigned_max)


def advance_pitch_slot(run: WorkshopRun, settings: WorkshopSettings, reference_time=None) -> bool:
    if run.current_section is None:
        return False
    if run.timer_status not in (WorkshopRun.TIMER_RUNNING, WorkshopRun.TIMER_PAUSED):
        return False

    section_duration = max(0, int(run.current_section.duration_seconds or 0))
    if section_duration == 0:
        return False

    now = reference_time or timezone.now()
    if run.timer_status == WorkshopRun.TIMER_RUNNING:
        if run.end_at is None:
            return False
        remaining = max(0, math.ceil((run.end_at - now).total_seconds()))
    else:
        remaining = max(0, int(run.paused_remaining_seconds or 0))

    elapsed = max(0, section_duration - remaining)
    group_count = _pitch_group_count(settings)
    pitch_seconds = 60
    gap_seconds = 10

    target_elapsed = None
    cursor = 0
    for group in range(1, group_count + 1):
        pitch_end = cursor + pitch_seconds
        if elapsed < pitch_end:
            target_elapsed = pitch_end
            break
        cursor = pitch_end

        if group < group_count:
            gap_end = cursor + gap_seconds
            if elapsed < gap_end:
                target_elapsed = gap_end
                break
            cursor = gap_end

    if target_elapsed is None:
        return False

    new_remaining = max(0, section_duration - target_elapsed)
    if new_remaining == remaining:
        return False

    if run.timer_status == WorkshopRun.TIMER_RUNNING:
        run.end_at = now + timedelta(seconds=new_remaining)
        run.save(update_fields=['end_at'])
    else:
        run.paused_remaining_seconds = new_remaining
        run.save(update_fields=['paused_remaining_seconds'])

    return True


def move_to_previous_section(run: WorkshopRun, keep_running: bool = False, reference_end_at=None) -> None:
    if run.current_section is None and run.timer_status != WorkshopRun.TIMER_COMPLETED:
        return

    previous_section = previous_enabled_section(run.current_section)

    if previous_section is None:
        run.timer_status = WorkshopRun.TIMER_READY
        run.current_section = None
        run.end_at = None
        run.paused_remaining_seconds = 0
        run.completed_at = None
        run.save()
        return

    run.current_section = previous_section
    run.paused_remaining_seconds = 0
    run.completed_at = None

    if keep_running:
        base = reference_end_at or timezone.now()
        run.timer_status = WorkshopRun.TIMER_RUNNING
        run.end_at = base + timedelta(seconds=previous_section.duration_seconds)
    else:
        run.timer_status = WorkshopRun.TIMER_READY
        run.end_at = None

    run.save()


def reconcile_run(run: WorkshopRun) -> None:
    if run.timer_status != WorkshopRun.TIMER_RUNNING or run.end_at is None:
        return

    now = timezone.now()
    if run.end_at > now:
        return

    reference_end = run.end_at
    while run.timer_status == WorkshopRun.TIMER_RUNNING and run.end_at and run.end_at <= now:
        next_section = next_enabled_section(run.current_section)

        if next_section is None:
            run.timer_status = WorkshopRun.TIMER_COMPLETED
            run.current_section = None
            run.end_at = None
            run.paused_remaining_seconds = 0
            run.completed_at = reference_end
            break

        run.current_section = next_section
        run.paused_remaining_seconds = 0
        reference_end = reference_end + timedelta(seconds=next_section.duration_seconds)
        run.end_at = reference_end

    run.save()


def sector_for_group(group_number: int) -> str:
    sector_names = list(Sector.objects.order_by('order', 'id').values_list('name', flat=True))
    if not sector_names:
        return f'Sector {group_number}'

    index = (group_number - 1) % len(sector_names)
    cycle = ((group_number - 1) // len(sector_names)) + 1
    base_name = sector_names[index]
    if cycle == 1:
        return base_name
    return f'{base_name} ({cycle})'


def calculate_group_count(settings: WorkshopSettings, joined_count: int) -> int:
    target = max(1, settings.target_group_size)
    predicted_groups = math.ceil(settings.predicted_class_size / target)
    turnout_groups = math.ceil(joined_count / target) if joined_count > 0 else 1
    return max(1, predicted_groups, turnout_groups)


def choose_group_number(group_count: int) -> int:
    counts = {group: 0 for group in range(1, group_count + 1)}
    for row in StudentAssignment.objects.values('group_number').annotate(total=Count('id')):
        if row['group_number'] in counts:
            counts[row['group_number']] = row['total']

    return min(counts, key=lambda group: (counts[group], group))


def claim_assignment(name: str, run: WorkshopRun, settings: WorkshopSettings) -> AssignmentResult:
    cleaned_name = ' '.join(name.strip().split())
    if not cleaned_name:
        raise ValueError('Name is required.')

    if not run.join_open:
        raise ValueError('Join is currently closed.')

    normalized = StudentAssignment.normalize_name(cleaned_name)
    existing = StudentAssignment.objects.filter(normalized_name=normalized).first()
    if existing:
        return AssignmentResult(assignment=existing, created=False)

    existing_max_group = StudentAssignment.objects.aggregate(max_group=Max('group_number'))['max_group'] or 0
    joined_after_claim = StudentAssignment.objects.count() + 1
    group_count = max(calculate_group_count(settings, joined_after_claim), existing_max_group)
    group_number = choose_group_number(group_count)
    sector_name = sector_for_group(group_number)

    try:
        assignment = StudentAssignment.objects.create(
            name=cleaned_name,
            normalized_name=normalized,
            group_number=group_number,
            sector_name=sector_name,
        )
    except IntegrityError:
        assignment = StudentAssignment.objects.get(normalized_name=normalized)
        return AssignmentResult(assignment=assignment, created=False)

    return AssignmentResult(assignment=assignment, created=True)


def run_phase(run: WorkshopRun) -> str:
    if run.timer_status == WorkshopRun.TIMER_COMPLETED:
        return 'completed'
    if run.current_section is None:
        return 'allocation'
    return 'timed'
