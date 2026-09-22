# Classroom Activity Pack Agent

Generates original **printable classroom exercise packs**, not storybooks.
Gemini writes the activities; optional Groq fallback handles text failures.
Python/WeasyPrint draws the worksheets and assembles A4 PDFs. There is no database.

## What each pack includes

- An illustrated cover, student activities, and exactly one final answer page.
- 6 student worksheets for Pre-K-K / 1st-2nd, or 8 for 3rd-4th / 5th-6th.
- No teacher guide, teaching tips, or separate teacher worksheets. Total: 8 or 10 PDF pages.
- At least three task types, chosen to suit the grade: counting, arithmetic, matching,
  sorting cards, informational reading, outlined-word tracing, creative design, and
  illustrated multiple-choice situations (at least two pages per pack).
- Large, colorful visual supports for young learners; restrained accents and
  more text/reasoning for older learners. White workspaces keep printing practical.

These are actual student tasks with answer space, not lists of ideas. Gemini/Groq
writes illustration briefs alongside the exercises. Cloudflare generates original
scene pictures, matching pairs, sorting objects, and tracing pictures. Python embeds
the art without cropping and renders all text, choices, equations and response areas.
For counting, one generated object is repeated the exact required number of times.
Identical briefs are reused within a pack. Depending on task mix, expect roughly
15-35 image requests per pack, rather than one image per PDF page. Provider quotas
apply; free daily capacity is not guaranteed. Missing art fails the pack explicitly.
The same cast/style brief is sent on every request; exact character consistency is
not guaranteed. Review that pictures agree with questions before using or selling.

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
- `IMAGE_PROVIDER=cloudflare` (default).
- `CLOUDFLARE_ACCOUNT_ID`: your 32-character account ID, not an API token.
- `CLOUDFLARE_API_TOKEN`: a token with Workers AI permission for that account.
- `CLOUDFLARE_IMAGE_STEPS=4` (default, permitted 1-8).
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
never in GitHub, chat, or screenshots. Image credentials are required again on BOTH
services. Set `IMAGE_PROVIDER=openai` with `OPENAI_API_KEY` only if you explicitly
want paid OpenAI illustrations; there is no automatic paid fallback.
Optional `.railway/railway.ts` is for CLI
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
docker run --rm -p 8080:8080 -e GEMINI_API_KEY -e CLOUDFLARE_ACCOUNT_ID -e CLOUDFLARE_API_TOKEN classroom-agent
```

Tests use mocked API responses and original deterministic exercise fixtures; they
do not spend API credits. Offline PDF tests check all four grade layouts. Layout
overflow is rejected rather than silently hiding content. Live content and account
quotas must still be tested after deployment.

Content-validation retries preserve valid pages and request complete replacements
only for failed pages, including their image briefs and answers. The current draft
is also preserved across text-provider fallback within the run. Logs identify the
page/item and failed constraint; the final error retains earlier validation failures
instead of hiding them behind the last provider error. Integer strings such as
`"12"` are normalized, but out-of-range values and fractions are never clamped or
rounded. Short passages are regenerated with their questions, not padded. HTTP 429
switches to the configured fallback without immediate same-provider retries. This
does not remove provider quotas or guarantee recovery during outages.

## Main modules

- `core/calendar_rules.py`: exact periods and timezone-aware today.
- `core/theme_picker.py`: current-event / evergreen themes and random grade batches.
- `core/activity_generator.py`: complete exercise JSON, constraints and computed keys.
- `core/activity_pdf.py`: illustrated worksheets and one final answer page.
- `core/activity_images.py`: per-task illustration briefs, reuse, and temporary assets.
- `core/pipeline.py`: shared activity generation and atomic PDF output.
- `core/providers.py`: Gemini/Groq/OpenAI text routing and sanitized errors.
- `core/book_library.py`, `core/delivery.py`, `core/state_manager.py`: storage.
- `cron_job.py`, `webhook_server.py`: scheduled and on-demand entry points.

Legacy story modules are retained for compatibility; the active pipeline reuses
the image backend for activity art. `DAILY_BOOK_COUNT` and `/books` keep their existing names
to avoid breaking your Railway configuration and download links.
