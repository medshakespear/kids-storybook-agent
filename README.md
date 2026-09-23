# Classroom Activity Pack Agent

Generates original **printable classroom exercise packs**, not storybooks.
Gemini plans the activities AND authors their page layouts. Cloudflare supplies original illustrations. Python/WeasyPrint
validates and assembles the model-authored designs as A4 PDFs. There is no database.

## What each pack includes

- An illustrated cover, student activities, and exactly one final answer page.
- 8 student worksheets for Pre-K-K / 1st-2nd, or 10 for 3rd-4th / 5th-6th.
- No teacher guide, teaching tips, or separate teacher worksheets. Total: **10 or 12 PDF pages**.
- The original **The Classroom Activity Collection** store logo appears on the cover.
- Original activity concepts and compositions chosen by the AI from the grade,
  theme, and teacher description. There is no hardcoded exercise-type menu or
  required repeating count/match/sort sequence.
- Large, colorful visual supports for young learners; restrained accents and
  more text/reasoning for older learners. White workspaces keep printing practical.

These are actual student tasks with answer space, not lists of ideas. A planning
call chooses distinct learning activities and their visual compositions. Separate
calls author the cover and each student page using restricted HTML/inline CSS,
with a pack-specific palette and 1-4 original illustration briefs per page.
Python supplies page boundaries, checks supported markup and printable bounds,
embeds artwork without cropping, and adds the single consolidated answer page.
Cloudflare produces the artwork; Gemini decides what the art should show.
Identical briefs are reused within a pack. Expect 10-12 design calls before retries
and up to 36-44 image calls, depending on grade and design, plus one visual-review
call per batch of up to four distinct images. Rejected images get up to two targeted
regenerations by default, each followed by another review. Provider quotas
apply; free daily capacity is not guaranteed. Missing art fails the pack explicitly.
The same cast/style brief is sent on every request; exact character consistency is
not guaranteed. Automated visual review catches some errors but is not proof of
correctness. Review that pictures agree with questions before using or selling.

## Faster generation, branding, and image checks

Independent cover/student designs run in parallel after a single shared plan.
Illustrations also run in parallel and keep their original page/asset ordering.
Default concurrency is deliberately limited, and PDF rendering is serialized to
keep the font/layout libraries safe. Logs report design, image generation, visual
review, PDF assembly, and total elapsed time so slow stages are visible.

The original logo is bundled at `assets/store-logo.png` and embedded directly by
Python. Its bytes are unchanged; trusted cover CSS trims the surrounding white
margin in the displayed layout. The AI does not redraw it. A 41mm header is
reserved before the generated cover content, including during layout checks.
Existing PDFs remain unchanged; these settings apply to newly generated packs.

After Cloudflare generates illustrations, the configured text provider (Gemini by
default) receives the **actual PNG images**, original prompts, relevant worksheet
HTML, and answers. It checks scene/task agreement, objects, relationships, visible
quantity mistakes, anatomy, unwanted lettering, cropped subjects, and age suitability.
Images used on several pages include every usage context in their review. Checks
run in batches of up to four images. Only rejected images are regenerated, up to
`IMAGE_REPAIR_ATTEMPTS` times (default 2), using the latest corrected prompt, then
reviewed again against the original requirements. Approved assets are retained.
The reviewer receives the previous attempt's prompt and defects to make subsequent
corrections more specific. Task-critical scene instructions are never shortened
to accommodate decorative style text. Each asset is assessed for its own role,
without demanding that it contain other images or elements supplied by HTML.
If review is unavailable, returns invalid verdicts twice, or still rejects an
image after regeneration, the pack fails explicitly instead of publishing
unchecked artwork. Remaining failures name the image ID, affected activities,
PDF page numbers, and specific defects. Webhook errors also return an
`image_review_failures` list with those details. The `image_review.regenerated`
success count measures regeneration calls, including repeated repairs of one image.
The selected text model must support image inputs. No new
API service or API key is required. The webhook returns `image_review`,
`page_count`, and `generation_seconds` along with its download link.

Optional performance variables on **both** Railway services:

| Variable | Default | Allowed | Purpose |
| --- | --- | --- | --- |
| `DESIGN_WORKERS` | `3` | 1-4 | Independent page-design requests |
| `IMAGE_WORKERS` | `3` | 1-4 | Independent image-generation requests |
| `REVIEW_WORKERS` | `2` | 1-3 | Concurrent image-review batches |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` | `45` | 10-120 | Timeout for each text/vision request |
| `GEMINI_CALL_BUDGET_SECONDS` | `90` | 15-300 | Budget for starting/retrying one completion |
| `GEMINI_TRANSIENT_ATTEMPTS` | `2` | 1-3 | Attempts per slot for temporary failures |
| `IMAGE_REQUEST_TIMEOUT_SECONDS` | `60` | 15-180 | Cloudflare response timeout |
| `IMAGE_REPAIR_ATTEMPTS` | `2` | 1-3 | Targeted regeneration rounds per rejected image |

These defaults work without adding variables. If your project's small rate limit
cannot support parallel calls, reduce the three worker settings to `1`.
An in-flight HTTP call remains governed by its transport timeouts; the completion
budget prevents further retries after it is spent, not a strict whole-book deadline.
Image requests have two attempts by default. Actual runtime depends on provider
latency, quotas, artwork count, repairs and review; **three-minute generation is
not guaranteed**, especially for longer packs with image checks. Vision review
uses additional Gemini quota, and regenerations use additional image quota.

The PDFs are static and are NOT editable forms or personalized name books.
No automatic class-name personalization is supplied. Originality and varied layouts
are requested, not guarantees of novelty or professional design quality.
Before selling or teaching, review content, answer keys, cultural context, reading
level, and print quality. In this flexible design mode, mathematical and semantic
correctness are model-authored and require human review; the former fixed-type
arithmetic checker is not used. Layout checks cannot detect every visual or
educational flaw. No standards alignment is claimed.

## Daily selection: random events in the next 30 days

1. Resolve today in `BOOK_TIMEZONE` (default UTC).
2. Include event periods overlapping today through today + 30 days, inclusive.
   This includes an ongoing month/week and events starting within the window.
3. Randomly choose an eligible event, then one of its theme angles, per book.
   Events with more angles do not receive extra selection weight.
4. Avoid recently used theme/grade pairs where possible and shuffle grade bands
   in balanced groups of four.
5. If the entire window has no eligible events, use creative evergreen activities.

Year boundaries and movable holidays are handled by calendar rules.
Daily count remains `DAILY_BOOK_COUNT` (default 6-8; allowed 1-20).

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
- `GEMINI_API_KEY_1`: Google AI Studio key (legacy `GEMINI_API_KEY` also works).
- `GEMINI_TEXT_MODEL=gemini-3.5-flash-lite` (default).
- `IMAGE_PROVIDER=cloudflare` (default).
- `CLOUDFLARE_ACCOUNT_ID_1`: your 32-character account ID, not an API token.
- `CLOUDFLARE_API_TOKEN_1`: a token with Workers AI permission for that account.
  Legacy unnumbered Cloudflare variables also work.
- `CLOUDFLARE_IMAGE_STEPS=4` (default, permitted 1-8).
- `BOOK_TIMEZONE=UTC`, or e.g. `Africa/Casablanca` / `America/New_York`.
  Set the same value on web and cron. Railway's cron schedule is still in UTC.

Groq has been removed. Delete `GROQ_API_KEY`, `GROQ_TEXT_MODEL`, and
`TEXT_FALLBACK_PROVIDER` from Railway; set `TEXT_PROVIDER=gemini` on both services.
Old Groq/fallback variables are ignored. Up to four Gemini keys and four Cloudflare
account/token pairs are supported; see the slot setup below.
Paid OpenAI text is opt-in with `TEXT_PROVIDER=openai` and `OPENAI_API_KEY`;
there is no automatic paid OpenAI fallback. Free quotas depend on your provider account.
The OpenAI Python SDK also transports Gemini requests; installing it does not
mean they go to OpenAI. Provider/model errors do not log raw response bodies or keys.
Explicit Railway model variables override code defaults; update old values on both services.

### Four credential slots on Railway

On **each** service (`web` and `cron`), open **Variables** and add these variables.
Enter actual secret values in Railway only, never in a committed file.

| Slot | Gemini key | Cloudflare token | Matching Cloudflare account ID |
| --- | --- | --- | --- |
| 1 | `GEMINI_API_KEY_1` | `CLOUDFLARE_API_TOKEN_1` | `CLOUDFLARE_ACCOUNT_ID_1` |
| 2 | `GEMINI_API_KEY_2` | `CLOUDFLARE_API_TOKEN_2` | `CLOUDFLARE_ACCOUNT_ID_2` |
| 3 | `GEMINI_API_KEY_3` | `CLOUDFLARE_API_TOKEN_3` | `CLOUDFLARE_ACCOUNT_ID_3` |
| 4 | `GEMINI_API_KEY_4` | `CLOUDFLARE_API_TOKEN_4` | `CLOUDFLARE_ACCOUNT_ID_4` |

1. Set `TEXT_PROVIDER=gemini` and `IMAGE_PROVIDER=cloudflare` on both services.
2. Add the slots you have; one through four are supported, and gaps are allowed.
   A token's Cloudflare account ID must belong to the account it can access.
3. Remove `GROQ_API_KEY`, `GROQ_TEXT_MODEL`, and `TEXT_FALLBACK_PROVIDER`.
4. Deploy both services with the latest GitHub commit and saved variable changes.
5. Keep `DAILY_BOOK_COUNT=1` on cron for the first run. Trigger one run and check
   for slot labels, `SUCCESS`, and `DELIVERED`; then open `/books` to download it.

The existing unnumbered Gemini key and Cloudflare token serve as **slot 1 aliases**.
An explicit `_1` key/token takes precedence, so the old value is not a fifth slot.
A common `CLOUDFLARE_ACCOUNT_ID` may supply the account for any token missing an
explicit numbered account ID. Otherwise every configured token needs its paired ID.
Duplicate Gemini keys or identical Cloudflare token/account pairs are used once.

Each process starts at the first configured slot and keeps using a healthy slot.
An HTTP 429 puts it on cooldown and retries the **same API request** with the next
available slot. Successful text designs and illustrations already in that running
pack are retained. Rejected credentials (401/403) are skipped until configuration
changes or the process restarts. Validation errors repair the same design using
the healthy key; invalid prompts/models do not cycle through all credentials.
For Gemini connection/timeouts, HTTP 408/409, and 5xx errors (including 503), retry
the same slot up to two total attempts by default with exponential backoff and jitter, then
cool it down and try the next configured slot with the unchanged request. There
are at most 8 HTTP attempts per completion by default with four slots, subject to
the 90-second retry budget; the content-repair
loop does not restart an exhausted pool. Cloudflare network/5xx errors retain
their existing bounded retries. No new environment variables are needed.

`API_KEY_COOLDOWN_SECONDS` defaults to **60** (allowed 1-86400). A longer provider
`Retry-After` or Gemini `RetryInfo` delay takes precedence. Cloudflare's explicit
daily-allocation error waits until its midnight UTC reset. If every slot is
unavailable, generation returns a clear error; it never loops through keys forever
or silently switches to paid OpenAI. Cooldowns are shared by requests within one
process, but are not persisted or coordinated between web and cron. Restarting a
process does not reset the provider's quota. Each run has a fresh local pool.
For Gemini temporary errors, a server delay longer than 10 seconds cools that slot
immediately instead of holding the worker asleep; shorter server delays are
honored before its next retry. A 503 does not permanently disable a key. A
provider-wide outage can affect every key, so failover cannot guarantee success;
if all slots fail, retry the run later. See Google's
[retry guidance](https://ai.google.dev/gemini-api/docs/troubleshooting#retry-strategy).

**More keys do not guarantee more quota.** Gemini limits apply per project; if
multiple keys belong to the same project, set matching `GEMINI_PROJECT_ID_1` through
`GEMINI_PROJECT_ID_4` values so the pool cools those keys together. These are optional
project identifiers, not secrets. Cloudflare tokens for the same account always
share its cooldown automatically. Use credentials and capacity you are authorized
to use; slot rotation does not increase a provider's allowance.
See [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) and
[Cloudflare Workers AI limits](https://developers.cloudflare.com/workers-ai/platform/limits/).
Logs identify only the provider and slot number, never the credential values.

### Storage and delivery

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
- `POST /generate`: generate ONE original pack from `description`, `link`, or both.
  Does not scrape or copy the reference product; omitted grade uses history rotation.

```json
{"link": "https://example.com/classroom-sorting-activities", "grade_band": "1st-2nd"}
```

For a detailed creative brief, no link is required:

```json
{
  "description": "Create a colorful garden detective pack. Children investigate plant needs, invent a watering tool, and draw a comic ending. Use varied illustrated page compositions with generous drawing space.",
  "grade_band": "1st-2nd"
}
```

Descriptions accept up to 4,000 characters. Generation now involves multiple text
and illustration calls and can take longer than the old templates. Prefer cron for
long runs; a synchronous webhook can exceed an HTTP client's timeout. A disconnected
client should check `/books` before retrying, since the server may finish the pack.

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

Each creative unit (plan, cover, or one student page) has bounded retries with
validation feedback. Long answer keys are condensed separately after the student
layout passes; this never asks the model to redesign a valid worksheet. Short keys
need no extra request. All six HTML heading levels are supported. Each unit uses
validation feedback and the latest draft. Completed pages stay in memory when a
later page needs correction. Python assigns page order. All pages are print-checked
with fixed-size preview image boxes before illustration spending. Final PDFs are
checked again with real art. Model-authored code is never executed; scripts, file
links, external resource loads, and unsupported layout declarations are rejected.
Gemini and Cloudflare HTTP 429 move the failed request to the next available slot.
This does not remove quotas or guarantee recovery during outages. Interrupted runs
do not retain unfinished pages across container restarts.

## Main modules

- `core/calendar_rules.py`: exact periods and timezone-aware today.
- `core/theme_picker.py`: current-event / evergreen themes and random grade batches.
- `core/creative_generator.py`: AI activity planning, page design, repair and illustrations.
- `core/creative_layout.py`: restricted HTML/CSS, print preflight, final PDF and answer page.
- `core/image_review.py`: multimodal artwork review, selective regeneration, and final verdicts.
- `core/runtime.py`: bounded configuration and ordered parallel work.
- `core/pipeline.py`: shared activity generation and atomic PDF output.
- `core/providers.py`: Gemini/OpenAI text routing and sanitized errors.
- `core/credential_pool.py`: four-slot failover, cooldowns, and shared-quota handling.
- `core/book_library.py`, `core/delivery.py`, `core/state_manager.py`: storage.
- `cron_job.py`, `webhook_server.py`: scheduled and on-demand entry points.

Legacy story and fixed-template activity modules are retained for compatibility;
the active pipeline uses the creative engine and reuses the image backend.
`DAILY_BOOK_COUNT` and `/books` keep their existing names
to avoid breaking your Railway configuration and download links.
