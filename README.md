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

## Daily selection: 7–37 days ahead and keyword titles

1. Resolve today in `BOOK_TIMEZONE` (default UTC).
2. Include event periods overlapping **today + 7 through today + 37 days**, inclusive.
   For a run on October 7, the window is October 14–November 13. An ongoing month/week qualifies
   only if its period overlaps that future window; events ending earlier are excluded.
3. Randomly choose an eligible event, one of its `title_keywords`, then a theme angle.
   The selected keyword becomes the exact book/cover title and steers the readings.
   Events with more keywords/angles do not receive extra selection weight.
4. Avoid recently used theme/grade pairs where possible and shuffle grade bands
   in balanced groups of the two active bands.
5. Dated holidays/observances take priority. If none overlap, use a matching seasonal
   teaching theme; if there is none, use `evergreen_topics` such as Community Helpers.
   Seasons are labeled instructional windows, not invented holiday dates.

Year boundaries and movable holidays are handled by calendar rules.
Daily count remains `DAILY_BOOK_COUNT` (default 6-8; allowed 1-20).

`calendar.json` now contains exact schedule rules:
- `fixed`: actual annual month/day, not a substitute federal day.
- `month`: the whole named month, including leap days.
- `range`: inclusive month/day through end_month/end_day; supports year rollover.
- `nth_weekday` and `last_weekday`: Monday=0 through Sunday=6, recalculated each year.
  `offset_days` supports Grandparents Day (6 days after Labor Day) and Election Day
  (1 day after the first Monday in November).
- `easter`: Western/Gregorian Easter, with an optional offset (Mardi Gras = -47 days).
- `week_containing`: week containing a reference day, e.g. October 9.
- `dates`: explicit year-specific start/end ISO dates.

Lunar New Year, Diwali, Hanukkah and Passover have sourced year-specific dates for
2026–2027. Update those tables before later years; missing years are skipped rather than
guessed. Ramadan uses clearly marked community-dependent planning dates, including a
provisional 2027 window. Religious observance timing can vary; notes are passed to the text
generator. Local breaks and solstices remain disabled until verified dates are supplied.
Back to School is an August–September instructional theme, not a district opening date.
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
For Gemini connection/timeouts, HTTP 408/409 and 5xx errors (including 503), the
pool immediately tries the next available credential with the unchanged request.
Each pool round visits each slot once; temporary outages use short cooldowns,
while a supplied `Retry-After` is honored. The outer JSON call allows at most
`GEMINI_TRANSPORT_ATTEMPTS` pool rounds (default **3**) and shares a
`GEMINI_TRANSPORT_BUDGET_SECONDS` deadline (default **120 seconds**) across them.
A new pool round does not restart that deadline. `GEMINI_CALL_BUDGET_SECONDS`
(default 120) and `GEMINI_REQUEST_TIMEOUT_SECONDS` (default 40) further bound an
individual facade/HTTP request. Existing Railway variables override these defaults.
A successful HTTP response with invalid content starts a separate bounded content
repair budget; a provider outage does not consume a content-validation attempt.
Cloudflare retains its bounded network/5xx retries. No new variables are required.

`API_KEY_COOLDOWN_SECONDS` defaults to **60** (allowed 1-86400). A longer provider
`Retry-After` or Gemini `RetryInfo` delay takes precedence. Cloudflare's explicit
daily-allocation error waits until its midnight UTC reset. If every slot is
unavailable, generation returns a clear error; it never loops through keys forever
or silently switches to paid OpenAI. Cooldowns are shared by requests within one
process, but are not persisted or coordinated between web and cron. Restarting a
process does not reset the provider's quota. Each run has a fresh local pool.
Gemini server delays put the affected slot on cooldown while other slots may proceed.
If all slots are blocked, the next wait respects the earliest available cooldown and
the overall deadline; waits beyond that deadline stop the completion. A 503 does not permanently disable a key. A
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
- `GET /` or `/books`: activity library and generation form (also shows old PDFs).
- `GET /api/books`: public JSON catalog.
- `GET /output/<filename>.pdf`: download.
- `POST /generate`: generate ONE original pack from `description`, `link`, or both; alternatively supply `event` alone.
  Reads public page text for the topic/learning goal without copying the reference product.
  Omitted grade uses history rotation.
- `POST /generation-jobs`: same input, returns HTTP 202 with a `job_id` and `status_url`.
- `GET /generation-jobs/<job_id>`: queued/running/completed/failed status; completed jobs include the PDF link.

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

### Generate from the website

1. Open your Railway web service's public URL (the same page as `/books`).
2. Select **From a link** and paste a public product/page URL, or select **From a description** and explain your topic and learning goals. Select **From an event** to choose any enabled calendar event without supplying a link or description.
3. Choose **Grades 3–4** or **Grades 5–6**.
4. If `WEBHOOK_API_KEY` is configured, enter it in **Generation access key**. It is sent in the request header and is not stored in the browser or embedded in the page.
5. Click **Generate workbook**. Keep the page open while it polls progress, then click **Download PDF**. The completed book is also saved in the library.

Descriptions accept up to 4,000 characters. Link mode fetches actual HTML/text,
including page title and description. It does not execute JavaScript, sign in,
bypass site restrictions, or download referenced paid products. If a site blocks
access or provides too little readable text, generation stops with a clear error;
paste a description instead. Page data is treated as untrusted inspiration, not
instructions. Public-address checks, DNS-pinned connections, checked redirects,
request timeouts and a 1 MB response limit protect the fetch endpoint.

The browser uses a background queue (one running job and one waiting job) so a
long generation does not require a long-lived POST connection. Job status is
transient memory, not a database. Use the documented **one-worker** Gunicorn
command; multiple workers do not share these jobs. Service restarts interrupt
unfinished jobs, and completed job records expire after an hour on the next
submission. Completed PDFs and their catalog records persist through the existing
storage/state mechanism. If you close the page or lose connection, check `/books`
before submitting again. No automatic duplicate generation is started.

The existing synchronous `POST /generate` still returns `title`, `grade_band`,
`resource_type: "activity_pack"`, `pdf_path`, and `download_url`. It may take minutes.
Set `WEBHOOK_API_KEY` on web and supply `X-API-Key` for both generation APIs and
job polling to prevent strangers consuming your quota. The library/downloads
remain public. The UI needs no new API service or environment variables.

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
52 characters, with 160mm-high uncropped artwork and no printed description. A pastel
background with curved coral, teal and lilac shapes frames the store logo, rounded title panel,
grade band and concise feature strip. Decoration is local SVG, not AI-generated typography.

### Independent answer verification

After all passage/choice repairs and editorial review, a separate text-only solve receives
just the passage, printed question prompts and A–D choices. It cannot see the proposed
answer key, evidence quotations or explanations. It can report no valid option or multiple
valid options. Detected mismatches trigger repairs of only the affected numbered questions;
the passage and other questions remain frozen. Ordinary mismatches allow two repair rounds
followed by one fresh replacement (four blind solves total). An ambiguous question instead
triggers an immediate full rewrite of its stem and all four choices, preserving its reading
skill. Rejected stems and choices cannot be recycled with casing or punctuation changes.
If ambiguity is detected, recovery allows at most six blind solves and five bounded
repair/replacement attempts. Extra calls occur only for this recovery path. The replacement
sees the frozen passage, accepted questions and rejected wording, rather than complete faulty
question objects. Every replacement must pass another blind solve. Unresolved defects still stop PDF
publication before image spending. Question repair uses the same scoped choice-length,
evidence and explanation-wording helpers as initial generation. The log reports the
expected/reviewer letters, quality flags and specific review reason for each failed question.
Concise final key explanations come from the independent solve. Longer reviewer reasons
remain intact for diagnostics and question repairs; they do not invalidate an otherwise
valid solve or replace the existing validated, print-sized explanation. Balanced letter relabeling
then moves each correct option together with its key letter. This is model-based semantic
review, not a guarantee of correctness or an external factual verification service.

Reading workbooks now explicitly use the activity-art prompt path instead of the recurring
storybook-character style. Cover art is based on a reviewed reading scene rather than the
product title, with explicit no-lettering and no-generic-costume instructions. There is still
no Gemini image reviewer; inspect the final illustrations before selling.

The independent text solve also audits whether inference questions actually require an
unstated conclusion and whether distractors are plausible misunderstandings of the passage.
Quality defects trigger the same bounded, question-only repair as incorrect answers.
Balanced keys avoid three identical consecutive letters and use at least three letters per
five-question set. Bullying passages receive additional checks for potential repetition and
prompt adult reporting without witness/documentation prerequisites. Illustration scene prompts
replace text-prone display surfaces with plain surfaces and request closed unmarked books.
No image reviewer is used; image generators can still violate prompts, so visually inspect
the final PDF before listing it for sale.

### Editing keyword titles

Each calendar entry has `title_keywords` (a JSON list of title strings, each at most
52 characters). `keyword_topics` may map individual titles to a more specific reading
context. For example, Halloween randomly selects Halloween Activities, Halloween Craft
or Halloween Bulletin Board, and every unit must address that selected context. The
cover still says Reading Comprehension: these keywords do not introduce a craft template
or bulletin-board kit. Titles, dates, selected window and keywords are recorded in cron
logs and successful state/catalog records. Webhook requests keep their existing generated
titles; the automatic keyword-title rule applies to calendar-driven cron books.

`selection_window` in `calendar.json` defines inclusive start/end offsets (defaults 7/37).
Dated events, seasonal themes and evergreen subjects are separate. Search-volume/rank
numbers do not become book titles or affect the random event probability. Synonyms such
as Hanukkah/Chanukah and Day of the Dead/Dia de los Muertos share one event.

Manual event API example: `{"event":"Halloween","grade_band":"3rd-4th"}`.
The same body works with `POST /generate` and `POST /generation-jobs`. Event mode
rejects a simultaneous link/description and offers all enabled calendar entries,
regardless of the cron window. Disabled entries are not offered. A matching title
keyword and angle are selected within the chosen event.

Daily batches now choose **one event** overlapping days **7–37 ahead**, inclusive,
and generate the configured number of books for that event across the active grade
bands. Titles and angles can vary within it. Days 0–6 are excluded; an ongoing
month qualifies if its period overlaps the future window.
