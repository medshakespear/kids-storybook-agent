"""Flask web service for on-demand classroom activity-pack generation."""

from __future__ import annotations

import logging
import json
import hmac
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4
import time
import random

from flask import Flask, jsonify, request, send_from_directory, url_for, render_template

from core.book_library import list_books, register_book, receive_pdf
from core.paths import OUTPUT_DIR, CALENDAR_PATH, ensure_runtime_directories
from core.grade_policy import ACTIVE_GRADE_BANDS
from core.pipeline import generate_book, load_grade_config
from core.state_manager import load_state
from core.theme_picker import pick_webhook_grade_band
from core.reference_reader import read_reference, reference_context, ReferenceReadError


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
logging.basicConfig(stream=sys.stdout, level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
ensure_runtime_directories()


def _authorized() -> bool:
    """Validate the optional webhook API key."""

    expected = os.environ.get("WEBHOOK_API_KEY")
    return not expected or request.headers.get("X-API-Key") == expected


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    """Return service health for Railway checks."""

    return {"status": "ok"}, 200


def generator_events():
    """List enabled calendar themes for manual selection, independent of cron dates."""
    with Path(CALENDAR_PATH).open(encoding='utf-8') as handle:
        calendar = json.load(handle)
    return sorted([event for event in calendar['events'] if event.get('enabled',True) and event.get('theme_angles')],key=lambda event:event['event_name'])


def generation_input(payload):
    """Validate a generation brief before starting network or AI work."""
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')
    link, description = payload.get('link', ''), payload.get('description', '')
    if link is None:
        link = ''
    if not isinstance(description, str) or len(description) > 4000:
        raise ValueError('description must be text of at most 4000 characters.')
    if not isinstance(link, str) or len(link) > 2048:
        raise ValueError('link must be a URL string.')
    link, description = link.strip(), description.strip()
    if link:
        try:
            parsed = urlparse(link)
            valid = parsed.scheme in {'http','https'} and parsed.hostname and not parsed.username and not parsed.password
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('link must be a valid public http or https URL.')
    event_name = payload.get('event', '')
    if not isinstance(event_name,str) or len(event_name)>200:
        raise ValueError('event must be a calendar event name.')
    event_name = event_name.strip()
    event = None
    if event_name:
        if link or description:
            raise ValueError('Choose an event only when no description or link is supplied.')
        event = next((item for item in generator_events() if item['event_name']==event_name),None)
        if event is None:
            raise ValueError('Choose an enabled event from the calendar.')
    if not link and not description and event is None:
        raise ValueError('Provide a description, a reference link, or a calendar event.')
    grade_config = load_grade_config()
    band = payload.get('grade_band')
    if band is None:
        band = pick_webhook_grade_band(load_state())
    if not isinstance(band,str) or band not in ACTIVE_GRADE_BANDS or band not in grade_config:
        raise ValueError('Only 3rd-4th and 5th-6th grade bands are enabled.')
    return dict(link=link, description=description, grade_band=band, grade_config=grade_config, event=event)


def run_generation(brief):
    """Read a reference when supplied and use the shared generation/delivery pipeline."""
    context = reference_context(read_reference(brief['link'])) if brief['link'] else ''
    if brief['description']:
        context += '\nTeacher creative brief: ' + brief['description']
    theme = 'Original reading comprehension workbook based on the supplied educational brief.'
    title_options = {}
    event = brief.get('event')
    if event:
        chooser = random.SystemRandom()
        keyword = chooser.choice(event.get('title_keywords') or [event['event_name']])
        theme = keyword + ': ' + chooser.choice(event['theme_angles'])
        context = 'Selected calendar event: ' + event['event_name'] + '\nTitle keyword: ' + keyword
        context += '\n' + event.get('keyword_topics',{}).get(keyword,'') + '\n' + event.get('note','')
        title_options['book_title'] = keyword
    story, pdf_path = generate_book(
        theme=theme, grade_band=brief['grade_band'], source_context=context,
        grade_config=brief['grade_config'], **title_options)
    if event:
        story['event_name'] = event['event_name']
        story['selection_mode'] = 'manual_event' 
    register_book(story,pdf_path.name,'On demand')
    return dict(status='completed',title=story['title'],resource_type='activity_pack',
                grade_band=brief['grade_band'],pdf_path='/output/'+pdf_path.name,
                download_url='/output/'+pdf_path.name,
                **{key:story.get(key) for key in ('page_count','image_review','image_validation','content_checks','generation_seconds')})


def request_brief():
    """Read the authenticated JSON body shared by both generation endpoints."""
    if not _authorized():
        return None, (jsonify(error='Unauthorized. Supply a valid X-API-Key header.'),401)
    if not request.is_json:
        return None, (jsonify(error='Request body must be JSON.'),415)
    try:
        return generation_input(request.get_json(silent=True)), None
    except ValueError as exc:
        return None, (jsonify(error=str(exc),allowed_grade_bands=list(ACTIVE_GRADE_BANDS)),400)


@app.post('/generate')
def generate():
    """Keep the synchronous POST API for existing integrations."""
    brief, error = request_brief()
    if error:
        return error
    try:
        result = run_generation(brief)
        result['download_url'] = request.host_url.rstrip('/') + result['download_url']
        return jsonify(result)
    except ReferenceReadError as exc:
        return jsonify(error='Reference page could not be read.',detail=str(exc)),422
    except Exception as exc:
        logger.exception('On-demand generation failed')
        return jsonify(error='Activity-pack generation failed.',detail=str(exc),image_review_failures=getattr(exc,'failures',[])),500


# Transient job status is kept in memory; only completed books persist in state.json.
# Railway's documented web command uses one worker with multiple HTTP threads.
_jobs, _jobs_lock = {}, Lock()
_job_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='web-generation')


def perform_job(job_id, brief):
    """Complete one background request and record its result without exposing secrets."""
    with _jobs_lock:
        _jobs[job_id].update(status='running',message='Reading the reference and generating your workbook.' if brief['link'] else 'Generating your workbook from the selected event.' if brief.get('event') else 'Generating your workbook from the description.')
    try:
        result = run_generation(brief)
    except Exception as exc:
        logger.exception('Background workbook generation failed')
        result = dict(status='failed',error='Reference page could not be read.' if isinstance(exc,ReferenceReadError) else 'Activity-pack generation failed.',detail=str(exc))
    with _jobs_lock:
        _jobs[job_id].update(result,updated=time.monotonic())


@app.post('/generation-jobs')
def start_generation_job():
    """Return immediately and let the browser poll a bounded background queue."""
    brief, error = request_brief()
    if error:
        return error
    with _jobs_lock:
        now = time.monotonic()
        for job_id in list(_jobs):
            if _jobs[job_id]['status'] in {'completed','failed'} and now-_jobs[job_id]['updated'] > 3600:
                del _jobs[job_id]
        if sum(j['status'] in {'queued','running'} for j in _jobs.values()) >= 2:
            return jsonify(error='Generation is busy. Please wait for the current books to finish.'),429
        job_id = uuid4().hex
        _jobs[job_id] = dict(status='queued',message='Your workbook is queued.',updated=now)
        try:
            _job_worker.submit(perform_job,job_id,brief)
        except RuntimeError:
            del _jobs[job_id]
            return jsonify(error='Generation worker is unavailable. Retry shortly.'),503
    return jsonify(status='queued',job_id=job_id,status_url='/generation-jobs/'+job_id),202


@app.get('/generation-jobs/<job_id>')
def generation_job_status(job_id):
    """Return authenticated job progress or a completed PDF download path."""
    if not _authorized():
        return jsonify(error='Unauthorized. Supply a valid X-API-Key header.'),401
    with _jobs_lock:
        result = dict(_jobs.get(job_id,{}))
    if not result:
        return jsonify(error='Job not found. The service may have restarted; check the book library before retrying.'),404
    result.pop('updated',None)
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get("/output/<path:filename>")
def download_output(filename: str) -> object:
    """Serve a generated PDF from the configured output directory/volume."""

    if not filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are available."}), 404
    return send_from_directory(Path(OUTPUT_DIR).resolve(), filename, as_attachment=True)


@app.errorhandler(413)
def request_too_large(_: Exception) -> tuple[object, int]:
    """Return JSON when a request exceeds the configured limit."""

    return jsonify({"error": "Request body is too large."}), 413


@app.get("/")
@app.get("/books")
def books_page():
    """Show the public book library with download links."""
    return render_template("books.html", books=list_books(), key_required=bool(os.environ.get("WEBHOOK_API_KEY")), events=generator_events())


@app.get("/api/books")
def books_api():
    """Return all known books and file availability."""
    return jsonify(books=list_books())


@app.get("/internal/state")
def library_state():
    """Allow the cron service to read current rotation history."""
    if not delivery_authorized():
        return jsonify(error="Unauthorized"), 401
    return jsonify(load_state())


def delivery_authorized():
    """Require a configured shared secret for internal delivery endpoints."""
    expected = os.environ.get("DELIVERY_TOKEN", "")
    return bool(expected) and hmac.compare_digest(expected, request.headers.get("X-Delivery-Token", ""))


@app.post("/internal/books")
def upload_book():
    """Receive a cron PDF and metadata, with idempotent filename handling."""
    if not delivery_authorized():
        return jsonify(error="Unauthorized"), 401
    try:
        metadata = json.loads(request.form.get("metadata", "{}"))
        if not isinstance(metadata, dict) or "pdf" not in request.files:
            raise ValueError("A PDF and metadata object are required")
        filename = receive_pdf(request.files["pdf"], metadata)
        return jsonify(status="stored", filename=filename), 201
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
