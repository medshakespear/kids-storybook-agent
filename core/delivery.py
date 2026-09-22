"""Deliver daily PDFs to the web service's persistent volume."""
import json
import os
import time
from urllib.parse import urlparse
import requests


def delivery_settings():
    """Return validated optional delivery settings."""
    base = os.environ.get('BOOK_LIBRARY_URL', '').rstrip('/')
    token = os.environ.get('DELIVERY_TOKEN', '')
    if base and (urlparse(base).scheme != 'https' or not urlparse(base).hostname or not token):
        raise ValueError('BOOK_LIBRARY_URL must use HTTPS and DELIVERY_TOKEN must be set')
    return base, token


def fetch_library_state():
    """Read durable rotation state before spending money on a cron run."""
    base, token = delivery_settings()
    if not base:
        return None
    response = requests.get(base + '/internal/state', headers={'X-Delivery-Token': token}, timeout=30)
    response.raise_for_status()
    state = response.json()
    if not isinstance(state, dict) or not isinstance(state.get('generated'), list):
        raise ValueError('Library returned invalid state')
    return state


def deliver_book(story, pdf_path):
    """Upload a PDF with bounded retries; the server deduplicates by filename."""
    base, token = delivery_settings()
    if not base:
        return False
    metadata = {key: story[key] for key in ('title', 'theme', 'grade_band')}
    for key in ('resource_type', 'generated_on', 'event_name', 'event_date', 'event_end', 'selection_mode'):
        if key in story:
            metadata[key] = story[key]
    for attempt in range(4):
        try:
            with pdf_path.open('rb') as handle:
                response = requests.post(base + '/internal/books',
                    headers={'X-Delivery-Token': token},
                    data={'metadata': json.dumps(metadata)},
                    files={'pdf': (pdf_path.name, handle, 'application/pdf')}, timeout=180)
            response.raise_for_status()
            if response.json().get('filename') != pdf_path.name:
                raise ValueError('Library did not acknowledge the PDF')
            return True
        except (requests.RequestException, ValueError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return False
