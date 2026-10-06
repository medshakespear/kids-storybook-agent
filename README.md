# Classroom Reading and QCM Agent

Generates original illustrated reading-comprehension packs for **grades 3–6**.
Both cron and webhook use the reading engine. Active bands are `3rd-4th` and
`5th-6th`; younger-grade requests are rejected before API calls.

## What each pack includes

The default is **12 A4 pages**: a branded illustrated cover, five passage/question
pairs, and one final answer key. Each pair has one illustrated reading page and
one QCM (multiple-choice) page with five questions and four choices, A–D.
That gives **five passages and 25 questions per pack**. No teacher guide,
picture-counting puzzles, sorting worksheets, or unrelated arithmetic tasks.

| Band | Passage length | Reading focus |
| --- | --- | --- |
| 3rd-4th | 220–300 words | Main idea, details, vocabulary in context, inference, cause and effect |
| 5th-6th | 320–420 words | Evidence-based inference, author's purpose, text structure, vocabulary and comparisons |

Passages have 3–4 paragraphs. Each question set covers at least three reading
skills, including inference, with no more than two literal-detail questions.
Short or overlong passages receive a scoped passage rewrite with a measured word
target and retained evidence quotations. Overlong choices receive a batched rewrite
of only the failed choices; no text is padded or silently truncated. Valid units
need no extra repair calls. Missing or paraphrased evidence triggers a scoped repair
of only the affected questions, with the passage frozen. Harmless quote typography
and whitespace differences are normalized; invented wording remains invalid.
Long or missing answer explanations and question stems receive one batched wording
repair, retaining the passage, choices, evidence and correct letters. Titles and
image briefs use the same scoped character-limit handling. Explanations target
60–90 characters within the 110-character print limit; nothing is silently cut off.
Repairs still use bounded provider/validation retries.
Gemini generates content JSON and performs a second text-only comprehension
review. Python checks distinct options, answer letters, word counts and supporting
quotes that occur in the passage. The same reviewed object supplies student
questions and the final answer key. This reduces inconsistencies but cannot
prove factual accuracy or guarantee that every distractor is unambiguous.

Python supplies all HTML/CSS and checks actual printable bounds and font sizes;
Gemini no longer authors page layouts. Reading pages include relevant colorful
artwork; question pages keep a clean, readable layout. Questions are answered
from the passage, never by guessing quantities or details in AI artwork.
Cloudflare generates **six images** per default pack: one cover and five passage
illustrations. Local file checks remain; Gemini does not review images.
The original store logo at `assets/store-logo.png` is embedded on the cover.
Existing PDFs are unchanged. Review new content and answers before classroom use
or sale; these are static PDFs, not editable worksheets.

No new API key or setting is required for this format. Deploy the updated branch
on both Railway services. Four Gemini keys and four Cloudflare account/token
pairs remain supported. Quotas and provider outages can still stop generation.
`activity_pages=10` in each active grade configuration means ten student pages
(five pairs); it must be even. There is no database.

## Performance settings

One planning call plus five passage calls and five comprehension-review calls
are required before retries. Independent pairs and illustrations can run in
parallel. `DESIGN_WORKERS` and `IMAGE_WORKERS` default to `3` (range 1–4);
text workers are capped by configured credential capacity. Reduce to `1` for
small provider quotas. Real latency depends on provider response times and
retries; no fixed generation time is guaranteed.

## Daily selection: random events in the next 30 days

1. Resolve today in `BOOK_TIMEZONE` (default UTC).
2. Include event periods overlapping today through today + 30 days, inclusive.
   This includes an ongoing month/week and events starting within the window.
3. Randomly choose an eligible event, then one of its theme angles, per book.
   Events with more angles do not receive extra selection weight.
4. Avoid recently used theme/grade pairs where possible and shuffle grade bands
   in balanced groups of the two active bands.
5. If the entire window has no eligible events, use evergreen reading themes.

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
{"link": "https://example.com/garden-reading-comprehension", "grade_band": "3rd-4th"}
```

For a reading-topic brief, no link is required:

```json
{
  "description": "Create illustrated informational readings about plant needs, fair scientific tests and garden ecosystems. Include multiple-choice questions about inference, vocabulary and evidence.",
  "grade_band": "3rd-4th"
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

Python 3.11+ and WeasyPrint native libraries are required. The Dockerfile installs
native dependencies and fonts. Export provider credentials, then run:

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python webhook_server.py
# Separate terminal, with the same credentials:
DAILY_BOOK_COUNT=1 python cron_job.py
```

Tests mock provider responses and render original offline fixtures; they do not
spend API credits. Reading tests cover both active grade bands, content validation,
student layouts and the single final key. Legacy design tests remain for shared
renderer/backend compatibility. Live provider responses need a deployment test.
Generation has bounded validation feedback and transport retries. Failed requests
are reported without publishing a partial PDF. Completed units stay in memory
until the run finishes; interrupted runs do not resume after container restart.

## Main modules

- `core/reading_generator.py`: grade-specific passages, QCM, text review and deterministic layouts.
- `core/pipeline.py`: shared cron/webhook generation and atomic PDF output.
- `core/creative_layout.py`: print preflight, logo, PDF assembly and final answer key.
- `core/creative_generator.py`: shared JSON request/retry and illustration backend; its legacy creative pack entry point is no longer the production path.
- `core/providers.py`, `core/credential_pool.py`: provider routing, four-slot failover and cooldowns.
- `core/image_review.py`: local image integrity checks only.
- `core/calendar_rules.py`, `core/theme_picker.py`: dates, event selection and grade rotation.
- `core/book_library.py`, `core/delivery.py`, `core/state_manager.py`: storage and delivery.
- `cron_job.py`, `webhook_server.py`: scheduled and on-demand entry points.

Legacy story/puzzle modules are retained for compatibility. `DAILY_BOOK_COUNT`,
`/generate` and `/books` retain their names and existing request/download formats.


### Reading-pack quality and layout

Production packs serve grades 3–4 and 5–6. Each 12-page pack includes the store-logo cover,
five illustrated informational readings, five multiple-choice pages, and one final answer sheet.
Python lays out every page; the model supplies content rather than arbitrary HTML/CSS.
Square artwork is displayed without cropping, questions have clear answer labels, and the final
key prints a separate row for each answer and explanation. Correct choices are relabeled using
a shuffled balanced schedule; the shared content object keeps the question pages and key aligned.

Generation and independent text review now ask for concrete age-accessible writing, explained
vocabulary, and plausible passage-based distractors. A targeted passage rewrite catches extreme
sentence density and vague unsupported research claims before evidence checks. These are heuristic
checks, not certified reading-level scores or external fact checking. No AI image reviewer is used.
Before selling, review facts, question ambiguity, illustrations, and the final PDF yourself;
model review and local print checks cannot guarantee instructional accuracy or sales.

Workbook styling uses blue/gold accents, alternating question panels, numbered reading paragraphs,
and uncropped square illustrations (86mm for grades 3–4; 76mm for grades 5–6). To leave room for
larger illustrations and clearer paragraph spacing, passages use 220–280 words or 320–380 words
respectively. Product titles should describe the reading comprehension actually included. The text
review explicitly checks inference versus literal recall, plausible distractors, fictional example
labels, historical explanations, and overly absolute safety claims. Local repair catches selected
risky patterns; it does not replace factual verification by a person.

Each reading/question pair now has its own coordinated accent color (teal, coral, purple,
green or blue). Upper-grade large-area fills stay restrained. Question panels reserve a
consistent minimum height for a more balanced page. Covers request a title of at most
52 characters and a description of at most 110 characters, with 151mm-high uncropped
artwork, a colored grade band and a concise feature strip beneath the required store logo.

### Independent answer verification

After all passage/choice repairs and editorial review, a separate text-only solve receives
just the passage, printed question prompts and A–D choices. It cannot see the proposed
answer key, evidence quotations or explanations. It can report no valid option or multiple
valid options. Detected mismatches trigger repairs of only the affected numbered questions;
the passage and other questions remain frozen. Repaired questions are solved again, with
at most two repair rounds. Unresolved mismatches stop PDF publication before image spending.
The final key explanations come from the independent solve, and balanced letter relabeling
then moves each correct option together with its key letter. This is model-based semantic
review, not a guarantee of correctness or an external factual verification service.

Reading workbooks now explicitly use the activity-art prompt path instead of the recurring
storybook-character style. Cover art is based on a reviewed reading scene rather than the
product title, with explicit no-lettering and no-generic-costume instructions. There is still
no Gemini image reviewer; inspect the final illustrations before selling.
