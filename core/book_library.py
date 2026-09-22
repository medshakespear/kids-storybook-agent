"""Durable book catalog in the existing state.json, with atomic PDF delivery."""
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from threading import RLock

from core.paths import OUTPUT_DIR, STATE_PATH
from core.state_manager import load_state, save_state, update_state

LOCK = RLock()  # Run one Gunicorn worker; threads share this lock.


def register_book(story, filename, source):
    """Register a finished PDF exactly once in the single state file."""
    with LOCK:
        state = load_state()
        if any(item.get('filename') == filename for item in state['generated']):
            return
        update_state(state, theme=story['theme'], event_name=source,
                     grade_band=story['grade_band'], title=story['title'],
                     output_path=f'output/{filename}')
        state['generated'][-1].update(filename=filename, source=source)
        from core.theme_picker import GRADE_BANDS
        state['last_grade_band_index'] = GRADE_BANDS.index(story['grade_band'])
        save_state(state)


def list_books():
    """List catalog records and recover discoverable PDFs absent from old state."""
    with LOCK:
        records = list(load_state()['generated'])
    books = {}
    for item in records:
        filename = item.get('filename') or Path(item.get('output_path', '')).name
        if filename.endswith('.pdf'):
            books[filename] = {**item, 'filename': filename,
                               'available': (OUTPUT_DIR / filename).is_file()}
    for path in OUTPUT_DIR.glob('*.pdf'):
        if path.name not in books:
            books[path.name] = dict(filename=path.name, title=path.stem,
                                    grade_band='Unknown', source='Recovered PDF',
                                    generated_on=date.fromtimestamp(path.stat().st_mtime).isoformat(),
                                    available=True)
    return sorted(books.values(), key=lambda b: (b.get('generated_on', ''), b['filename']), reverse=True)


def receive_pdf(upload, metadata):
    """Validate an upload, atomically publish it, then register its metadata."""
    filename = upload.filename or ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,180}\.pdf', filename):
        raise ValueError('Invalid PDF filename')
    for key in ('title', 'theme', 'grade_band'):
        if not isinstance(metadata.get(key), str) or not 1 <= len(metadata[key]) <= 2000:
            raise ValueError(f'Invalid {key}')
    from core.theme_picker import GRADE_BANDS
    if metadata['grade_band'] not in GRADE_BANDS:
        raise ValueError('Invalid grade_band')
    with tempfile.NamedTemporaryFile(dir=OUTPUT_DIR, suffix='.part', delete=False) as temp:
        temporary = Path(temp.name)
    try:
        upload.save(temporary)
        with temporary.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise ValueError('File is not a PDF')
        with LOCK:
            destination = OUTPUT_DIR / filename
            if not destination.exists():
                os.replace(temporary, destination)
            register_book(metadata, filename, 'Daily cron')
    finally:
        temporary.unlink(missing_ok=True)
    return filename
