# Classroom Activity Pack Agent

Generates original **printable classroom exercise packs**, not storybooks.
Gemini writes the activities; optional Groq fallback handles text failures.
Python/WeasyPrint draws the worksheets and assembles A4 PDFs. There is no database.

## What each pack includes

- A colorful cover and teacher plan with learning goals, materials, and timing.
- 6 student worksheets for Pre-K-K / 1st-2nd, or 8 for 3rd-4th / 5th-6th.
- One separate teacher key per worksheet, with answers/sample responses, teaching tips,
  support, extension, and observation space. Total: 14 or 18 PDF pages.
- At least three task types, chosen to suit the grade: counting, arithmetic, matching,
  sorting cards, informational reading, outlined-word tracing, and creative design.
- Large, colorful visual supports for young learners; restrained accents and
  more text/reasoning for older learners. White workspaces keep printing practical.

These are actual student tasks with answer space, not lists of ideas. Counting art,
math answers, matching layouts, tracing letters, cards and diagrams are created by
code. **Activity generation makes no image API calls and needs no Cloudflare key.**
This avoids spending image quota or relying on AI pictures for exact quantities.
Existing Cloudflare/OpenAI image code remains available as legacy code, but the cron
and webhook do not call it. No new storybook is produced by these entry points.

The PDFs are static and are NOT editable forms or personalized name books.
Tracing uses outlined uppercase words, not a handwriting curriculum or automatic
class-name personalization. Originality is requested, not a guarantee of novelty.
Before selling or teaching, review content, answer keys, cultural context, reading
level, and print quality. Arithmetic/counting are checked in code; semantic answers
and educational suitability still require human review. No standards alignment is claimed.

## Daily selection: today, not upcoming events

1. Resolve today's date in `BOOK_TIMEZONE` (default `UTC`).
2. Match only calendar events whose inclusive start/end dates contain today.
3. If multiple events are active, vary the selected themes across the batch.
4. If none is active, select original evergreen classroom challenges.
5. Shuffle grade bands in groups of four, giving random order and balanced coverage.
6. Avoid recently used theme/grade pairs where possible; permit reuse when exhausted.

For example, September 22 can match Hispanic Heritage Month (September 15-October 15),
but not October's Fire Prevention Week. There is no 1-4-week lookahead or nearest-event
fallback. Daily count remains `DAILY_BOOK_COUNT` (default random 6-8; allowed 1-20).

`calendar.json` now contains exact schedule rules:
- `fixed`: actual annual month/day, not a substitute federal day.
- `month`: the whole named month, including leap days.
- `range`: inclusive month/day through end_month/end_day; supports year rollover.
- `nth_weekday` and `last_weekday`: Monday=0 through Sunday=6, recalculated each year.
- `week_containing`: week containing a reference day, e.g. October 9.
- `dates`: explicit year-specific start/end ISO dates.

Local/annually announced events (back to school, seasonal breaks, solstices,
Lunar New Year, etc.) are **disabled until verified dates are supplied**.
They are not guessed from old approximate anchors. Example school period:

```json
{
  "event_name": "Back to School",
  "enabled": true,
  "schedule": {"kind": "dates", "years": {"2026": ["2026-08-24", "2026-08-28"]}},
  "theme_angles": ["Organizing supplies and learning classroom routines"]
}
```

Use your own actual district dates for that example. Calendar sources:
[OPM holidays](https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/),
[Hispanic Heritage Month](https://hispanicheritagemonth.gov/About),
[NFPA](https://www.nfpa.org/events/fire-prevention-week).

## Manual Railway setup (no CLI needed)

Connect this repository to two services. Both build with the included Dockerfile.

| Service | Start command | Schedule |
| --- | --- | --- |
| web | `sh -c 'exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 900 webhook_server:app'` | Always on |
| cron | `python cron_job.py` | `0 7 * * *` (07:00 UTC daily) |

Use **Never** as cron's restart policy. Keep one web replica and one Gunicorn worker.

Set on BOTH services:
- `TEXT_PROVIDER=gemini`
- `GEMINI_API_KEY`: Google AI Studio key.
- `GEMINI_TEXT_MODEL=gemini-3.5-flash-lite` (default).
- `GROQ_API_KEY`: optional; enables Groq fallback.
- `GROQ_TEXT_MODEL=openai/gpt-oss-20b` (default; runs on Groq, not OpenAI).
- `TEXT_FALLBACK_PROVIDER=none` to disable the optional Groq fallback.
- `BOOK_TIMEZONE=UTC`, or e.g. `Africa/Casablanca` / `America/New_York`.
  Set the same value on web and cron. Railway's cron schedule is still in UTC.

`TEXT_PROVIDER=groq` can use Groq directly without a Gemini key.
Paid OpenAI text is opt-in with `TEXT_PROVIDER=openai` and `OPENAI_API_KEY`;
there is no automatic paid OpenAI fallback. Free quotas depend on your provider account.
The OpenAI Python SDK also transports Gemini/Groq requests; installing it does not
mean they go to OpenAI. Provider/model errors do not log raw response bodies or keys.
Explicit Railway model variables override code defaults; update old values on both services.

Storage and delivery:
1. Attach a persistent Volume to **web** at `/data`; set `DATA_DIR=/data`.
2. Set `DELIVERY_TOKEN` to the same long random secret on web and cron.
3. Generate a public domain for web in its networking settings.
4. On cron set `BOOK_LIBRARY_URL=https://your-web-domain` (no `/books` suffix).
5. Deploy the latest commit on BOTH services. Set `DAILY_BOOK_COUNT=1` on cron
   for your first test, run once, and look for `SUCCESS` and `DELIVERED` in logs.
6. Open `https://your-web-domain/books` to download the activity pack.
7. After reviewing it, change the daily count or remove the test override.

Old PDFs and state history are preserved. No volume or database migration is needed.
Web stores `/data/output/*.pdf` and its catalog in the single `/data/state.json`.
Cron reads that state and uploads each completed PDF via authenticated delivery.
Without a volume, web files are ephemeral. Web and cron do NOT share a filesystem.
If delivery fails, the local cron PDF has no durable retry queue: recover it before
that container disappears. Never remove the web volume merely to deploy new code.

`GITHUB_TOKEN` with Contents read/write, `GITHUB_REPOSITORY`, and optional
`GITHUB_BRANCH=main` enable cron's optional state commit-back. Without these,
volume-backed catalog/rotation still works. Secrets belong in Railway Variables,
never in GitHub, chat, or screenshots. Existing image-provider variables may remain;
the new activity pipeline ignores them. Optional `.railway/railway.ts` is for CLI
users; manual website configuration above is the recommended path.

## Web API

- `GET /health`: health check.
- `GET /` or `/books`: public activity library (also shows old PDFs).
- `GET /api/books`: public JSON catalog.
- `GET /output/<filename>.pdf`: download.
- `POST /generate`: generate ONE original exercise pack from URL slug inspiration.
  Does not scrape or copy the reference product; omitted grade uses history rotation.

```json
{"link": "https://example.com/classroom-sorting-activities", "grade_band": "1st-2nd"}
```

Response includes `title`, `grade_band`, `resource_type: "activity_pack"`,
`pdf_path`, and `download_url`. Generation is synchronous and may take minutes.
Set `WEBHOOK_API_KEY` on web and supply `X-API-Key` when calling `/generate`
to prevent strangers consuming your quota. The library/downloads remain public.

`GET /internal/state` and `POST /internal/books` require `X-Delivery-Token`;
only cron uses them. Each uploaded filename is registered once. New metadata records
the resource type, event period, and whether selection was event-based or evergreen.

## Local development and checks

Python 3.11+ and WeasyPrint's native libraries are required. The Dockerfile installs
native dependencies and fonts. Export provider keys in your shell, then:

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python webhook_server.py
# In another invocation, with the same exported environment:
DAILY_BOOK_COUNT=1 python cron_job.py
```

Or build and run Docker, passing the exported credentials:

```bash
docker build -t classroom-agent .
docker run --rm -p 8080:8080 -e GEMINI_API_KEY classroom-agent
```

Tests use mocked API responses and original deterministic exercise fixtures; they
do not spend API credits. Offline PDF tests check all four grade layouts. Layout
overflow is rejected rather than silently hiding content. Live content and account
quotas must still be tested after deployment.

## Main modules

- `core/calendar_rules.py`: exact periods and timezone-aware today.
- `core/theme_picker.py`: current-event / evergreen themes and random grade batches.
- `core/activity_generator.py`: complete exercise JSON, constraints and computed keys.
- `core/activity_pdf.py`: code-drawn visual worksheets and teacher pages.
- `core/pipeline.py`: shared activity generation and atomic PDF output.
- `core/providers.py`: Gemini/Groq/OpenAI text routing and sanitized errors.
- `core/book_library.py`, `core/delivery.py`, `core/state_manager.py`: storage.
- `cron_job.py`, `webhook_server.py`: scheduled and on-demand entry points.

Legacy story/image modules are retained for compatibility and tests only; the active
pipeline does not use them. `DAILY_BOOK_COUNT` and `/books` keep their existing names
to avoid breaking your Railway configuration and download links.
