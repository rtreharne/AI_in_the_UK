from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from datetime import timedelta

import qrcode
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from qrcode.image.svg import SvgPathImage

from .models import Sector, StudentAssignment, WorkshopRun, WorkshopSection, WorkshopSettings, WorkshopVote
from .services import (
    claim_assignment,
    move_to_previous_section,
    move_to_next_section,
    pause_timer,
    reconcile_run,
    run_phase,
    sector_for_group,
    running_remaining_seconds,
    start_timer,
)

FACILITATOR_SESSION_KEY = 'facilitator_unlocked'
ASIMOV_TEST_NAMES = [
    'Hari Seldon',
    'Gaal Dornick',
    'Salvor Hardin',
    'Hober Mallow',
    'Bayta Darell',
    'Toran Darell',
    'Arkady Darell',
    'The Mule',
    'Han Pritcher',
    'Ebling Mis',
    'Bel Riose',
    'Gladia Delmarre',
    'R Daneel Olivaw',
    'R Giskard Reventlov',
    'Elijah Baley',
    'R Jander Panell',
    'Susan Calvin',
    'Pieter Campanel',
    'Bel Arvardan',
    'Janov Pelorat',
    'Sura Novi',
    'Preem Palver',
    'Dors Venabili',
    'Yugo Amaryl',
    'Eto Demerzel',
    'Wanda Seldon',
    'Raych Seldon',
    'Chetter Hummin',
]


def _control_pin() -> str:
    return os.environ.get('WORKSHOP_CONTROL_PIN', '1234')


def _json_body(request: HttpRequest) -> dict:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _is_facilitator(request: HttpRequest) -> bool:
    return bool(request.session.get(FACILITATOR_SESSION_KEY, False))


def _forbidden() -> JsonResponse:
    return JsonResponse({'error': 'Facilitator PIN unlock required.'}, status=403)


def _section_title_matches(section: WorkshopSection | None, *keywords: str) -> bool:
    if not section:
        return False
    title = section.title.lower()
    return all(keyword.lower() in title for keyword in keywords)


def _eligible_vote_sectors() -> list[str]:
    sector_names = list(
        StudentAssignment.objects.order_by('group_number', 'created_at').values_list('sector_name', flat=True)
    )
    return list(dict.fromkeys(sector_names))


def _vote_results_payload(sector_catalog: list[str]) -> dict:
    counts = {
        row['sector_name']: row['total']
        for row in WorkshopVote.objects.values('sector_name').annotate(total=Count('id'))
    }

    by_sector = [
        {
            'sector_name': sector_name,
            'votes': int(counts.get(sector_name, 0)),
        }
        for sector_name in sector_catalog
    ]

    extras = sorted(name for name in counts if name not in set(sector_catalog))
    for sector_name in extras:
        by_sector.append({'sector_name': sector_name, 'votes': int(counts[sector_name])})

    ranked = sorted(by_sector, key=lambda row: (-row['votes'], row['sector_name']))
    total_votes = int(sum(row['votes'] for row in ranked))
    top_votes = int(ranked[0]['votes']) if ranked else 0
    leaders = [row['sector_name'] for row in ranked if row['votes'] == top_votes and top_votes > 0]

    return {
        'total_votes': total_votes,
        'top_votes': top_votes,
        'leaders': leaders,
        'tie': len(leaders) > 1,
        'winner_sector': leaders[0] if len(leaders) == 1 else None,
        'ranked': ranked,
    }


def _state_payload(request: HttpRequest) -> dict:
    run = WorkshopRun.get_solo()
    reconcile_run(run)
    run.refresh_from_db()

    settings = WorkshopSettings.get_solo()

    assignments = list(StudentAssignment.objects.order_by('group_number', 'created_at'))

    current_section = None
    if run.current_section:
        current_section = {
            'id': run.current_section.id,
            'order': run.current_section.order,
            'title': run.current_section.title,
            'description': run.current_section.description,
            'duration_seconds': run.current_section.duration_seconds,
        }

    sections = list(
        WorkshopSection.objects.filter(enabled=True)
        .order_by('order', 'id')
        .values('id', 'order', 'title', 'description', 'duration_seconds')
    )
    sector_catalog = list(Sector.objects.order_by('order', 'id').values_list('name', flat=True))
    vote_results = _vote_results_payload(_eligible_vote_sectors())

    return {
        'phase': run_phase(run),
        'join_open': run.join_open,
        'timer_status': run.timer_status,
        'remaining_seconds': running_remaining_seconds(run),
        'beep_enabled': run.beep_enabled,
        'current_section': current_section,
        'sections': sections,
        'sector_catalog': sector_catalog,
        'vote_open': _section_title_matches(run.current_section, 'vote', 'feedback'),
        'vote_results': vote_results,
        'facilitator_unlocked': _is_facilitator(request),
        'server_time': timezone.now().isoformat(),
        'join_url': request.build_absolute_uri(reverse('join_page')),
        'vote_url': request.build_absolute_uri(reverse('vote_page')),
        'joined_count': len(assignments),
        'settings': {
            'predicted_class_size': settings.predicted_class_size,
            'target_group_size': settings.target_group_size,
        },
        'assignments': [
            {
                'name': assignment.name,
                'group_number': assignment.group_number,
                'sector_name': assignment.sector_name,
            }
            for assignment in assignments
        ],
    }


def _make_qr_svg(data: str) -> str:
    qr = qrcode.QRCode(box_size=8, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    stream = io.BytesIO()
    image.save(stream)
    return stream.getvalue().decode('utf-8')


@require_GET
def display_page(request: HttpRequest) -> HttpResponse:
    join_url = request.build_absolute_uri(reverse('join_page'))
    vote_url = request.build_absolute_uri(reverse('vote_page'))
    context = {
        'join_url': join_url,
        'join_qr_svg': _make_qr_svg(join_url),
        'vote_url': vote_url,
        'vote_qr_svg': _make_qr_svg(vote_url),
    }
    return render(request, 'workshop/display.html', context)


@require_GET
def join_page(request: HttpRequest) -> HttpResponse:
    return render(request, 'workshop/join.html')


@require_GET
def vote_page(request: HttpRequest) -> HttpResponse:
    sectors = _eligible_vote_sectors()
    return render(request, 'workshop/vote.html', {'sectors': sectors})


@require_GET
def api_state(request: HttpRequest) -> JsonResponse:
    return JsonResponse(_state_payload(request))


@require_GET
def api_sound_gong(request: HttpRequest) -> HttpResponse:
    gong_path = Path(settings.BASE_DIR) / 'gong.mp3'
    if not gong_path.exists():
        raise Http404('Gong audio file not found.')

    return FileResponse(gong_path.open('rb'), content_type='audio/mpeg')


@require_GET
def api_sound_edith(request: HttpRequest) -> HttpResponse:
    edith_path = Path(settings.BASE_DIR) / 'edith.mp3'
    if not edith_path.exists():
        raise Http404('Edith audio file not found.')

    return FileResponse(edith_path.open('rb'), content_type='audio/mpeg')


@require_GET
def api_sound_drumroll(request: HttpRequest) -> HttpResponse:
    drumroll_path = Path(settings.BASE_DIR) / 'drumroll.mp3'
    if not drumroll_path.exists():
        raise Http404('Drumroll audio file not found.')

    return FileResponse(drumroll_path.open('rb'), content_type='audio/mpeg')


@require_GET
def api_sound_kool(request: HttpRequest) -> HttpResponse:
    kool_path = Path(settings.BASE_DIR) / 'kool.mp3'
    if not kool_path.exists():
        raise Http404('Kool audio file not found.')

    return FileResponse(kool_path.open('rb'), content_type='audio/mpeg')


@csrf_exempt
@require_POST
def api_vote_submit(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    selected_sector = ' '.join(str(payload.get('sector_name', '')).strip().split())
    if not selected_sector:
        return JsonResponse({'error': 'Please choose a sector.'}, status=400)
    feedback_text = str(payload.get('feedback_text', '')).strip()
    if not feedback_text:
        return JsonResponse({'error': 'Please add session feedback.'}, status=400)
    if len(feedback_text) > 200:
        return JsonResponse({'error': 'Feedback must be 200 characters or fewer.'}, status=400)

    try:
        session_rating = int(payload.get('session_rating'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Please provide a rating from 1 to 5.'}, status=400)
    if session_rating < 1 or session_rating > 5:
        return JsonResponse({'error': 'Rating must be between 1 and 5.'}, status=400)

    run = WorkshopRun.get_solo()
    reconcile_run(run)
    run.refresh_from_db()
    if not _section_title_matches(run.current_section, 'vote', 'feedback'):
        return JsonResponse({'error': 'Voting is only open during Vote and Feedback.'}, status=400)

    eligible_sectors = _eligible_vote_sectors()
    if selected_sector not in eligible_sectors:
        return JsonResponse({'error': 'Invalid sector selected.'}, status=400)

    WorkshopVote.objects.create(
        sector_name=selected_sector,
        session_rating=session_rating,
        feedback_text=feedback_text,
    )
    return JsonResponse({'ok': True, 'vote_results': _vote_results_payload(eligible_sectors)})


@csrf_exempt
@require_POST
def api_pin_unlock(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    pin = str(payload.get('pin', '')).strip()
    if pin != _control_pin():
        return JsonResponse({'error': 'Incorrect PIN.'}, status=403)

    request.session[FACILITATOR_SESSION_KEY] = True
    request.session.modified = True
    return JsonResponse({'ok': True})


@csrf_exempt
@require_POST
def api_control_start(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    with transaction.atomic():
        run = WorkshopRun.get_solo()
        try:
            start_timer(run)
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)

    return JsonResponse(_state_payload(request))


@csrf_exempt
@require_POST
def api_control_pause(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    with transaction.atomic():
        run = WorkshopRun.get_solo()
        pause_timer(run)

    return JsonResponse(_state_payload(request))


@csrf_exempt
@require_POST
def api_control_next(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    with transaction.atomic():
        run = WorkshopRun.get_solo()
        keep_running = run.timer_status == WorkshopRun.TIMER_RUNNING
        move_to_next_section(run, keep_running=keep_running, reference_end_at=timezone.now())

    return JsonResponse(_state_payload(request))


@csrf_exempt
@require_POST
def api_control_back(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    with transaction.atomic():
        run = WorkshopRun.get_solo()
        keep_running = run.timer_status == WorkshopRun.TIMER_RUNNING
        move_to_previous_section(run, keep_running=keep_running, reference_end_at=timezone.now())

    return JsonResponse(_state_payload(request))


@csrf_exempt
@require_POST
def api_join_open(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    with transaction.atomic():
        run = WorkshopRun.get_solo()
        run.join_open = True
        run.save()

    return JsonResponse(_state_payload(request))


@csrf_exempt
@require_POST
def api_join_close(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    with transaction.atomic():
        run = WorkshopRun.get_solo()
        run.join_open = False
        run.save()

    return JsonResponse(_state_payload(request))


@csrf_exempt
@require_POST
def api_run_reset(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    with transaction.atomic():
        StudentAssignment.objects.all().delete()
        WorkshopVote.objects.all().delete()
        run = WorkshopRun.get_solo()
        run.reset()

    return JsonResponse(_state_payload(request))


@csrf_exempt
@require_POST
def api_assignment_claim(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    name = str(payload.get('name', ''))

    run = WorkshopRun.get_solo()
    settings = WorkshopSettings.get_solo()

    try:
        result = claim_assignment(name=name, run=run, settings=settings)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    assignment = result.assignment
    return JsonResponse(
        {
            'created': result.created,
            'assignment': {
                'name': assignment.name,
                'group_number': assignment.group_number,
                'sector_name': assignment.sector_name,
            },
        }
    )


@require_GET
def api_assignments_csv(request: HttpRequest) -> HttpResponse:
    if not _is_facilitator(request):
        return HttpResponse('Facilitator PIN unlock required.', status=403)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Group', 'Sector'])
    for assignment in StudentAssignment.objects.order_by('group_number', 'created_at'):
        writer.writerow([assignment.name, assignment.group_number, assignment.sector_name])

    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="assignments.csv"'
    return response


@csrf_exempt
@require_POST
def api_beep_toggle(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    payload = _json_body(request)
    requested = payload.get('enabled')

    with transaction.atomic():
        run = WorkshopRun.get_solo()
        if isinstance(requested, bool):
            run.beep_enabled = requested
        else:
            run.beep_enabled = not run.beep_enabled
        run.save()

    return JsonResponse(_state_payload(request))


@csrf_exempt
@require_POST
def api_test_populate_asimov(request: HttpRequest) -> JsonResponse:
    if not _is_facilitator(request):
        return _forbidden()

    groups = 7
    per_group = 4

    if len(ASIMOV_TEST_NAMES) < groups * per_group:
        return JsonResponse({'error': 'Not enough test names configured.'}, status=500)

    with transaction.atomic():
        StudentAssignment.objects.all().delete()

        index = 0
        for group_number in range(1, groups + 1):
            sector_name = sector_for_group(group_number)
            for _ in range(per_group):
                name = ASIMOV_TEST_NAMES[index]
                index += 1
                StudentAssignment.objects.create(
                    name=name,
                    normalized_name=StudentAssignment.normalize_name(name),
                    group_number=group_number,
                    sector_name=sector_name,
                )

    return JsonResponse(_state_payload(request))
