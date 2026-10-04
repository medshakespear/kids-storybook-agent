"""Integration checks for delivery, persistence, and downloadable catalog entries."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import webhook_server as web
from core import book_library, state_manager


class LibraryTests(unittest.TestCase):
    """Exercise Flask endpoints with isolated storage and no AI calls."""

    def test_delivery_download_retry_and_restart(self):
        """A delivered PDF survives rereads and repeated delivery is deduplicated."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            state_path = output / 'state.json'
            def read_state():
                """Read isolated persistent state."""
                return state_manager.load_state(state_path)
            def write_state(value):
                """Write isolated persistent state."""
                return state_manager.save_state(value, state_path)
            with patch.dict('os.environ', {'DELIVERY_TOKEN': 'test-secret'}), \
                 patch.object(book_library, 'OUTPUT_DIR', output), \
                 patch.object(web, 'OUTPUT_DIR', output), \
                 patch.object(book_library, 'load_state', read_state), \
                 patch.object(book_library, 'save_state', write_state), \
                 patch.object(web, 'load_state', read_state):
                client = web.app.test_client()
                self.assertEqual(client.post('/internal/books').status_code, 401)
                self.assertIn(b'No completed books', client.get('/books').data)
                metadata = json.dumps(dict(title='<script>Fox</script>', theme='Earth Day', grade_band='3rd-4th',
                    resource_type='activity_pack', selection_mode='active_event', event_name='Earth Day',
                    event_date='2026-04-22', event_end='2026-04-22', generated_on='2026-04-22'))
                for _ in range(2):
                    response = client.post('/internal/books', headers={'X-Delivery-Token': 'test-secret'}, data={
                        'metadata': metadata, 'pdf': (io.BytesIO(b'%PDF-1.7\nfixture'), '2026_3rd-4th_fox.pdf')})
                    self.assertEqual(response.status_code, 201)
                fresh_client = web.app.test_client()
                self.assertEqual(len(fresh_client.get('/api/books').json['books']), 1)
                self.assertEqual(len(read_state()['generated']), 1)
                record = read_state()['generated'][0]
                self.assertEqual(record['resource_type'], 'activity_pack')
                self.assertEqual(record['selection_mode'], 'active_event')
                self.assertEqual(record['event_name'], 'Earth Day')
                self.assertEqual(record['generated_on'], '2026-04-22')
                self.assertIn(b'&lt;script&gt;', fresh_client.get('/').data)
                with fresh_client.get('/output/2026_3rd-4th_fox.pdf') as downloaded:
                    self.assertEqual(downloaded.data, b'%PDF-1.7\nfixture')
                invalid = client.post('/internal/books', headers={'X-Delivery-Token': 'test-secret'}, data={
                    'metadata': metadata, 'pdf': (io.BytesIO(b'not a PDF'), 'bad.pdf')})
                self.assertEqual(invalid.status_code, 400)
                traversal = client.post('/internal/books', headers={'X-Delivery-Token': 'test-secret'}, data={
                    'metadata': metadata, 'pdf': (io.BytesIO(b'%PDF-1.7'), '../bad.pdf')})
                self.assertEqual(traversal.status_code, 400)
                self.assertEqual(client.get('/internal/state').status_code, 401)
                self.assertEqual(client.get('/internal/state', headers={'X-Delivery-Token':'test-secret'}).status_code, 200)
