"""Local web entry point: shared storage, serialized generation and optional daily batches."""
from __future__ import annotations

from datetime import datetime
import logging
import os
import re
from threading import Event, RLock, Thread
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import jsonify

import cron_job
import webhook_server as web
from core.state_manager import load_state, save_state

app = web.app
LOGGER = logging.getLogger(__name__)
GENERATION_LOCK = RLock()
_original_generation = web.run_generation


def serialized_generation(brief):
    """Share one generation/state-write lock between local batches and web requests."""
    with GENERATION_LOCK:
        return _original_generation(brief)


web.run_generation = serialized_generation


def schedule_settings():
    """Validate the opt-in local schedule without contacting any AI service."""
    enabled = os.getenv('LOCAL_AUTO_DAILY', '0')
    clock = os.getenv('LOCAL_DAILY_TIME', '09:00')
    if enabled not in {'0', '1'}:
        raise ValueError('LOCAL_AUTO_DAILY must be 0 or 1')
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', clock):
        raise ValueError('LOCAL_DAILY_TIME must use HH:MM, for example 09:00')
    return enabled == '1', clock, ZoneInfo(os.getenv('BOOK_TIMEZONE', 'Africa/Casablanca'))


@app.context_processor
def local_context():
    """Expose local controls only when this entry point serves the existing dashboard."""
    enabled, clock, zone = schedule_settings()
    return dict(local_mode=True, local_daily_schedule=(clock + ' ' + str(zone)) if enabled else 'Manual only')


def perform_daily(job_id):
    """Run the cron pipeline in this process and publish its outcome to the web job tracker."""
    with web._jobs_lock:
        web._jobs[job_id].update(status='running', message='Generating the daily batch. Completed PDFs appear in the library.')
    with GENERATION_LOCK:
        today = datetime.now(schedule_settings()[2]).date().isoformat()
        state = load_state()
        before = len(state['generated'])
        state['local_daily'] = dict(attempted_on=today, started_at=datetime.now().astimezone().isoformat())
        save_state(state)
        try:
            exit_code = cron_job.main()
            state = load_state()
            count = max(0, len(state['generated']) - before)
            state['local_daily'].update(exit_code=exit_code, completed_at=datetime.now().astimezone().isoformat())
            save_state(state)
            result = dict(status='completed' if exit_code == 0 else 'failed', book_count=count,
                message=f'Daily batch finished: {count} workbook(s) saved. Refresh the library.', library_url='/books')
            if exit_code:
                result.update(error='Some or all daily books failed. Completed PDFs remain in the library.',
                              detail='Open View Logs.cmd for the generation errors.')
        except Exception:
            LOGGER.exception('Local daily batch failed')
            result = dict(status='failed', error='Daily batch failed. Open View Logs.cmd for details.', library_url='/books')
    with web._jobs_lock:
        web._jobs[job_id].update(result, updated=time.monotonic())


def queue_daily():
    """Queue one batch using the same bounded worker as on-demand workbook generation."""
    with web._jobs_lock:
        active = [j for j in web._jobs.values() if j['status'] in {'queued', 'running'}]
        if len(active) >= 2 or any(j.get('kind') == 'daily' for j in active):
            return None
        job_id = uuid4().hex
        web._jobs[job_id] = dict(kind='daily', status='queued', message='Daily batch queued.', updated=time.monotonic())
        try:
            web._job_worker.submit(perform_daily, job_id)
        except RuntimeError:
            del web._jobs[job_id]
            return None
    return dict(status='queued', job_id=job_id, status_url='/generation-jobs/' + job_id)


@app.post('/local/daily-run')
def daily_run():
    """Start a manual batch from the local web interface without blocking its HTTP request."""
    if not web._authorized():
        return jsonify(error='Unauthorized. Supply the generation access key.'), 401
    result = queue_daily()
    if result is None:
        return jsonify(error='Generation is busy. Wait for the current books to finish.'), 429
    return jsonify(result), 202


def daily_due(now, state, clock):
    """Run at most one scheduled attempt per local date, including after a late startup."""
    return (now.strftime('%H:%M') >= clock
            and state.get('local_daily', {}).get('attempted_on') != now.date().isoformat())


def scheduler_loop(stop):
    """Check the opt-in schedule while the computer and local service are running."""
    _, clock, zone = schedule_settings()
    while not stop.is_set():
        try:
            # Do not wait behind a long generation: the next tick can check it.
            if GENERATION_LOCK.acquire(blocking=False):
                try:
                    if daily_due(datetime.now(zone), load_state(), clock):
                        queue_daily()
                finally:
                    GENERATION_LOCK.release()
        except Exception:
            LOGGER.exception('Could not check the local daily schedule')
        stop.wait(30)


if schedule_settings()[0]:
    Thread(target=scheduler_loop, args=(Event(),), daemon=True, name='local-daily-scheduler').start()
