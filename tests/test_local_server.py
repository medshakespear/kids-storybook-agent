"""Exercise local UI, queued daily batches, persistent markers and serialized generation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ['LOCAL_AUTO_DAILY'] = '0'
import local_server as local
from core import book_library, state_manager


class LocalServerTests(unittest.TestCase):
    """No provider requests are needed to start or verify the local web interface."""

    def setUp(self):
        """Keep test history and generated PDFs separate from the repository."""
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'output'
        self.output.mkdir()
        self.state = self.root / 'state.json'
        self.load = lambda: state_manager.load_state(self.state)
        self.save = lambda state: state_manager.save_state(state, self.state)
        for target, value in ((local, dict(load_state=self.load, save_state=self.save)),
                              (book_library, dict(load_state=self.load, OUTPUT_DIR=self.output)),
                              (local.web, dict(OUTPUT_DIR=self.output))):
            control = patch.multiple(target, **value)
            control.start(); self.addCleanup(control.stop)
        self.env = patch.dict(os.environ, {'LOCAL_AUTO_DAILY':'0','LOCAL_DAILY_TIME':'09:00',
            'BOOK_TIMEZONE':'Africa/Casablanca','WEBHOOK_API_KEY':''})
        self.env.start(); self.addCleanup(self.env.stop)
        with local.web._jobs_lock:
            local.web._jobs.clear()
        self.client = local.app.test_client()

    def test_local_home_and_health_need_no_credentials_or_ai_calls(self):
        """Keep all existing workbook types, inputs and download controls in the local UI."""
        with patch.object(local, '_original_generation') as generate:
            self.assertEqual(self.client.get('/health').json, {'status':'ok'})
            response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        for text in ('Run daily batch','reading_qcm','varied_activities','reference-link','calendar-event','reading-topic'):
            self.assertIn(text, response.get_data(as_text=True))
        generate.assert_not_called()

    def test_daily_endpoint_respects_access_key_and_queue_capacity(self):
        """Manual batches use the same bounded generation queue as on-demand jobs."""
        with patch.dict(os.environ, WEBHOOK_API_KEY='local-test-key'), patch.object(local.web._job_worker,'submit') as submit:
            self.assertEqual(self.client.post('/local/daily-run').status_code, 401)
            first = self.client.post('/local/daily-run', headers={'X-API-Key':'local-test-key'})
            self.assertEqual(first.status_code, 202)
            self.assertEqual(self.client.post('/local/daily-run', headers={'X-API-Key':'local-test-key'}).status_code, 429)
            self.assertEqual(submit.call_count, 1)

    def test_daily_batch_marker_and_pdf_survive_in_the_local_library(self):
        """Run a mocked cron pipeline, then download a real rendered PDF from the web route."""
        def batch():
            """Simulate one successful persisted book using real PDF rendering."""
            from weasyprint import HTML
            HTML(string='<h1>Local workbook smoke test</h1><p>Saved on this computer.</p>').write_pdf(self.output/'local-book.pdf')
            state = self.load()
            state_manager.update_state(state,theme='Local smoke test',event_name='Local',grade_band='3rd-4th',
                title='Local workbook smoke test',output_path='output/local-book.pdf')
            self.save(state)
            return 0
        with patch.object(local.web._job_worker,'submit'):
            response = self.client.post('/local/daily-run')
        with patch.object(local.cron_job,'main',side_effect=batch):
            local.perform_daily(response.json['job_id'])
        status = self.client.get(response.json['status_url']).json
        self.assertEqual(status['status'], 'completed')
        self.assertEqual(status['book_count'], 1)
        state = self.load()
        self.assertEqual(state['local_daily']['exit_code'], 0)
        self.assertFalse(local.daily_due(datetime.now(ZoneInfo('Africa/Casablanca')).replace(hour=23,minute=59),state,'09:00'))
        books = self.client.get('/api/books').json['books']
        self.assertTrue(books[0]['available'])
        pdf = self.client.get('/output/local-book.pdf')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b'%PDF-'))
        pdf.close()

    def test_failed_scheduled_attempt_is_marked_without_discarding_history(self):
        """Failures do not auto-repeat paid requests all day; manual retry remains available."""
        with patch.object(local.web._job_worker,'submit'):
            response = self.client.post('/local/daily-run')
        with patch.object(local.cron_job,'main',return_value=2):
            local.perform_daily(response.json['job_id'])
        self.assertEqual(self.client.get(response.json['status_url']).json['status'], 'failed')
        self.assertEqual(self.load()['local_daily']['exit_code'], 2)

    def test_schedule_has_no_early_run_or_historical_backfill(self):
        """Use the configured local date for due checks rather than the container UTC date."""
        zone = ZoneInfo('Africa/Casablanca')
        self.assertFalse(local.daily_due(datetime(2026,10,27,8,59,tzinfo=zone),{},'09:00'))
        self.assertTrue(local.daily_due(datetime(2026,10,27,15,0,tzinfo=zone),{},'09:00'))
        self.assertFalse(local.daily_due(datetime(2026,10,27,15,0,tzinfo=zone),
            {'local_daily':{'attempted_on':'2026-10-27'}},'09:00'))
        for field,value in (('LOCAL_AUTO_DAILY','yes'),('LOCAL_DAILY_TIME','25:00')):
            with patch.dict(os.environ,{field:value}), self.assertRaises(ValueError):
                local.schedule_settings()

    def test_generation_is_serialized_in_the_single_local_process(self):
        """Concurrent API calls cannot race the daily pipeline's shared state writes."""
        first_started, second_started, release = Event(), Event(), Event()
        def generate(brief):
            """Hold one generation until the test confirms a second cannot enter."""
            if brief == 1:
                first_started.set()
                release.wait(3)
            else:
                second_started.set()
            return brief
        with patch.object(local,'_original_generation',side_effect=generate), ThreadPoolExecutor(2) as executor:
            first = executor.submit(local.serialized_generation,1)
            self.assertTrue(first_started.wait(1))
            second = executor.submit(local.serialized_generation,2)
            try:
                self.assertFalse(second_started.wait(.05))
            finally:
                release.set()
            self.assertEqual((first.result(),second.result()),(1,2))
