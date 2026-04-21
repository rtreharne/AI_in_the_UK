from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from .models import Sector, StudentAssignment, WorkshopRun, WorkshopSection, WorkshopSettings, WorkshopVote
from .services import claim_assignment, reconcile_run, start_timer


class TimerServiceTests(TestCase):
    def setUp(self):
        WorkshopSection.objects.create(order=1, title='First', description='', duration_seconds=5, enabled=True)
        WorkshopSection.objects.create(order=2, title='Second', description='', duration_seconds=5, enabled=True)
        WorkshopSection.objects.create(order=3, title='Third', description='', duration_seconds=5, enabled=True)
        WorkshopSettings.get_solo()

    def test_start_pause_resume(self):
        run = WorkshopRun.get_solo()

        start_timer(run)
        run.refresh_from_db()
        self.assertEqual(run.timer_status, WorkshopRun.TIMER_RUNNING)
        self.assertIsNotNone(run.end_at)

        run.end_at = timezone.now() + timedelta(seconds=4)
        run.save()

        from .services import pause_timer

        pause_timer(run)
        run.refresh_from_db()
        self.assertEqual(run.timer_status, WorkshopRun.TIMER_PAUSED)
        self.assertGreaterEqual(run.paused_remaining_seconds, 0)

        start_timer(run)
        run.refresh_from_db()
        self.assertEqual(run.timer_status, WorkshopRun.TIMER_RUNNING)

    def test_reconcile_advances_multiple_sections_and_completes(self):
        run = WorkshopRun.get_solo()
        start_timer(run)

        run.refresh_from_db()
        run.end_at = timezone.now() - timedelta(seconds=20)
        run.save()

        reconcile_run(run)
        run.refresh_from_db()

        self.assertEqual(run.timer_status, WorkshopRun.TIMER_COMPLETED)
        self.assertIsNone(run.current_section)
        self.assertIsNone(run.end_at)


class AssignmentServiceTests(TestCase):
    def setUp(self):
        Sector.objects.create(order=1, name='Healthcare')
        Sector.objects.create(order=2, name='Education')

        settings = WorkshopSettings.get_solo()
        settings.predicted_class_size = 4
        settings.target_group_size = 2
        settings.save()

        run = WorkshopRun.get_solo()
        run.join_open = True
        run.save()

    def test_balanced_assignment_and_sector_cycle(self):
        run = WorkshopRun.get_solo()
        settings = WorkshopSettings.get_solo()

        claims = [claim_assignment(name, run, settings).assignment for name in ['A', 'B', 'C', 'D', 'E']]

        self.assertEqual(claims[0].group_number, 1)
        self.assertEqual(claims[1].group_number, 2)
        self.assertEqual(claims[2].group_number, 1)
        self.assertEqual(claims[3].group_number, 2)
        self.assertEqual(claims[4].group_number, 3)

        self.assertEqual(claims[4].sector_name, 'Healthcare (2)')

    def test_rescan_returns_existing_assignment(self):
        run = WorkshopRun.get_solo()
        settings = WorkshopSettings.get_solo()

        first = claim_assignment('Alex', run, settings)
        second = claim_assignment(' alex ', run, settings)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.assignment.id, second.assignment.id)
        self.assertEqual(StudentAssignment.objects.count(), 1)


class ApiBehaviorTests(TestCase):
    def setUp(self):
        self.client = Client()

        WorkshopSection.objects.create(order=1, title='Intro', description='d', duration_seconds=60, enabled=True)
        WorkshopSection.objects.create(order=2, title='Pitch', description='d', duration_seconds=60, enabled=True)
        Sector.objects.create(order=1, name='Healthcare')
        settings = WorkshopSettings.get_solo()
        settings.predicted_class_size = 2
        settings.target_group_size = 2
        settings.save()
        WorkshopRun.get_solo()

    def unlock(self):
        return self.client.post('/api/pin/unlock', data='{"pin":"1234"}', content_type='application/json')

    def test_control_endpoints_require_pin_unlock(self):
        response = self.client.post('/api/control/start', data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/control/back', data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_vote_submit_rejected_outside_vote_section(self):
        response = self.client.post(
            '/api/vote/submit',
            data='{"sector_name":"Healthcare"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_join_open_close_and_claim(self):
        self.assertEqual(self.unlock().status_code, 200)

        open_response = self.client.post('/api/join/open', data='{}', content_type='application/json')
        self.assertEqual(open_response.status_code, 200)

        claim_response = self.client.post(
            '/api/assignment/claim',
            data='{"name":"Student One"}',
            content_type='application/json',
        )
        self.assertEqual(claim_response.status_code, 200)

        close_response = self.client.post('/api/join/close', data='{}', content_type='application/json')
        self.assertEqual(close_response.status_code, 200)

        blocked_claim = self.client.post(
            '/api/assignment/claim',
            data='{"name":"Student Two"}',
            content_type='application/json',
        )
        self.assertEqual(blocked_claim.status_code, 400)

    def test_csv_requires_unlock(self):
        response = self.client.get('/api/assignments.csv')
        self.assertEqual(response.status_code, 403)

        self.unlock()
        self.client.post('/api/join/open', data='{}', content_type='application/json')
        self.client.post('/api/assignment/claim', data='{"name":"Sam"}', content_type='application/json')

        csv_response = self.client.get('/api/assignments.csv')
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn('Name,Group,Sector', csv_response.content.decode('utf-8'))

    def test_state_reports_expected_timer_states(self):
        self.unlock()
        self.client.post('/api/join/close', data='{}', content_type='application/json')

        start_response = self.client.post('/api/control/start', data='{}', content_type='application/json')
        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.json()['timer_status'], 'running')

        pause_response = self.client.post('/api/control/pause', data='{}', content_type='application/json')
        self.assertEqual(pause_response.status_code, 200)
        self.assertEqual(pause_response.json()['timer_status'], 'paused')

    def test_back_moves_to_previous_section_and_then_allocation(self):
        self.unlock()

        start_response = self.client.post('/api/control/start', data='{}', content_type='application/json')
        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.json()['current_section']['title'], 'Intro')

        next_response = self.client.post('/api/control/next', data='{}', content_type='application/json')
        self.assertEqual(next_response.status_code, 200)
        self.assertEqual(next_response.json()['current_section']['title'], 'Pitch')

        back_response = self.client.post('/api/control/back', data='{}', content_type='application/json')
        self.assertEqual(back_response.status_code, 200)
        self.assertEqual(back_response.json()['current_section']['title'], 'Intro')
        self.assertEqual(back_response.json()['timer_status'], 'running')

        back_to_allocation = self.client.post('/api/control/back', data='{}', content_type='application/json')
        self.assertEqual(back_to_allocation.status_code, 200)
        self.assertIsNone(back_to_allocation.json()['current_section'])
        self.assertEqual(back_to_allocation.json()['timer_status'], 'ready')

    def test_gong_audio_endpoint_available(self):
        response = self.client.get('/api/sounds/gong.mp3')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('audio/mpeg'))

    def test_edith_audio_endpoint_available(self):
        response = self.client.get('/api/sounds/edith.mp3')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('audio/mpeg'))

    def test_drumroll_audio_endpoint_available(self):
        response = self.client.get('/api/sounds/drumroll.mp3')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('audio/mpeg'))

    def test_kool_audio_endpoint_available(self):
        response = self.client.get('/api/sounds/kool.mp3')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('audio/mpeg'))

    def test_vote_page_available(self):
        response = self.client.get('/vote')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Do not vote for your own sector', response.content.decode('utf-8'))

    def test_join_can_open_after_timer_started(self):
        self.unlock()
        self.client.post('/api/join/close', data='{}', content_type='application/json')
        start_response = self.client.post('/api/control/start', data='{}', content_type='application/json')
        self.assertEqual(start_response.status_code, 200)

        open_response = self.client.post('/api/join/open', data='{}', content_type='application/json')
        self.assertEqual(open_response.status_code, 200)
        self.assertTrue(open_response.json()['join_open'])

    def test_populate_asimov_creates_seven_groups_of_four(self):
        self.unlock()

        response = self.client.post('/api/test/populate-asimov', data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 200)

        assignments = list(StudentAssignment.objects.order_by('group_number', 'name'))
        self.assertEqual(len(assignments), 28)

        counts = {}
        for assignment in assignments:
            counts[assignment.group_number] = counts.get(assignment.group_number, 0) + 1

        self.assertEqual(sorted(counts.keys()), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(set(counts.values()), {4})


class IntegrationFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        WorkshopSection.objects.create(order=1, title='Section 1', description='', duration_seconds=5, enabled=True)
        WorkshopSection.objects.create(order=2, title='Section 2', description='', duration_seconds=5, enabled=True)
        Sector.objects.create(order=1, name='Healthcare')
        settings = WorkshopSettings.get_solo()
        settings.predicted_class_size = 2
        settings.target_group_size = 2
        settings.save()
        WorkshopRun.get_solo()

    def unlock(self):
        self.client.post('/api/pin/unlock', data='{"pin":"1234"}', content_type='application/json')

    def test_full_flow_from_join_to_complete(self):
        self.unlock()

        self.assertEqual(self.client.post('/api/run/reset', data='{}', content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post('/api/join/open', data='{}', content_type='application/json').status_code, 200)

        self.assertEqual(
            self.client.post('/api/assignment/claim', data='{"name":"One"}', content_type='application/json').status_code,
            200,
        )

        self.assertEqual(self.client.post('/api/join/close', data='{}', content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post('/api/control/start', data='{}', content_type='application/json').status_code, 200)

        run = WorkshopRun.get_solo()
        run.end_at = timezone.now() - timedelta(seconds=1)
        run.save()

        state_after_first_expiry = self.client.get('/api/state').json()
        self.assertEqual(state_after_first_expiry['timer_status'], 'running')
        self.assertEqual(state_after_first_expiry['current_section']['title'], 'Section 2')

        run.refresh_from_db()
        run.end_at = timezone.now() - timedelta(seconds=1)
        run.save()

        final_state = self.client.get('/api/state').json()
        self.assertEqual(final_state['phase'], 'completed')
        self.assertEqual(final_state['timer_status'], 'completed')

        back_from_completed = self.client.post('/api/control/back', data='{}', content_type='application/json')
        self.assertEqual(back_from_completed.status_code, 200)
        self.assertEqual(back_from_completed.json()['timer_status'], 'ready')
        self.assertEqual(back_from_completed.json()['current_section']['title'], 'Section 2')


class VoteAndAwardFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        WorkshopSection.objects.create(order=1, title='Preparation', description='', duration_seconds=5, enabled=True)
        WorkshopSection.objects.create(order=2, title='Vote and Feedback', description='', duration_seconds=5, enabled=True)
        WorkshopSection.objects.create(order=3, title='Award to best AI solution', description='', duration_seconds=5, enabled=True)
        Sector.objects.create(order=1, name='Healthcare')
        Sector.objects.create(order=2, name='Education')
        StudentAssignment.objects.create(
            name='A',
            normalized_name=StudentAssignment.normalize_name('A'),
            group_number=1,
            sector_name='Healthcare',
        )
        StudentAssignment.objects.create(
            name='B',
            normalized_name=StudentAssignment.normalize_name('B'),
            group_number=2,
            sector_name='Education',
        )
        WorkshopSettings.get_solo()
        WorkshopRun.get_solo()

    def unlock(self):
        self.client.post('/api/pin/unlock', data='{"pin":"1234"}', content_type='application/json')

    def test_votes_aggregate_and_show_in_award_section(self):
        self.unlock()
        self.client.post('/api/control/start', data='{}', content_type='application/json')
        self.client.post('/api/control/next', data='{}', content_type='application/json')

        vote_one = self.client.post(
            '/api/vote/submit',
            data='{"sector_name":"Healthcare","session_rating":5,"feedback_text":"Excellent session."}',
            content_type='application/json',
        )
        vote_two = self.client.post(
            '/api/vote/submit',
            data='{"sector_name":"Healthcare","session_rating":4,"feedback_text":"Really useful."}',
            content_type='application/json',
        )
        vote_three = self.client.post(
            '/api/vote/submit',
            data='{"sector_name":"Education","session_rating":3,"feedback_text":"Good overall."}',
            content_type='application/json',
        )

        self.assertEqual(vote_one.status_code, 200)
        self.assertEqual(vote_two.status_code, 200)
        self.assertEqual(vote_three.status_code, 200)
        self.assertEqual(WorkshopVote.objects.count(), 3)

        self.client.post('/api/control/next', data='{}', content_type='application/json')
        award_state = self.client.get('/api/state').json()

        self.assertEqual(award_state['current_section']['title'], 'Award to best AI solution')
        self.assertEqual(award_state['vote_results']['total_votes'], 3)
        self.assertEqual(award_state['vote_results']['winner_sector'], 'Healthcare')
        self.assertEqual(award_state['vote_results']['top_votes'], 2)
        self.assertFalse(award_state['vote_results']['tie'])

        self.client.post('/api/run/reset', data='{}', content_type='application/json')
        self.assertEqual(WorkshopVote.objects.count(), 0)

    def test_vote_requires_rating_and_feedback(self):
        self.unlock()
        self.client.post('/api/control/start', data='{}', content_type='application/json')
        self.client.post('/api/control/next', data='{}', content_type='application/json')

        missing_rating = self.client.post(
            '/api/vote/submit',
            data='{"sector_name":"Healthcare","feedback_text":"Nice."}',
            content_type='application/json',
        )
        self.assertEqual(missing_rating.status_code, 400)

        missing_feedback = self.client.post(
            '/api/vote/submit',
            data='{"sector_name":"Healthcare","session_rating":5}',
            content_type='application/json',
        )
        self.assertEqual(missing_feedback.status_code, 400)

    def test_vote_page_only_lists_sectors_with_group_members(self):
        StudentAssignment.objects.all().delete()
        StudentAssignment.objects.create(
            name='Only One',
            normalized_name=StudentAssignment.normalize_name('Only One'),
            group_number=1,
            sector_name='Healthcare',
        )

        response = self.client.get('/vote')
        page = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<option value="Healthcare">Healthcare</option>', page)
        self.assertNotIn('<option value="Education">Education</option>', page)
