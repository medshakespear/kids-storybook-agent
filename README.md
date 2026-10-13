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
Short passages receive an additions-only repair: Python retains the original
paragraphs and requests only the measured number of new words. Additions extend
selected paragraph endings or form a fourth concluding paragraph. The model cannot
delete evidence or rewrite existing facts during expansion. Retries report the
original count, added count and complete required addition range. Overlong passages
still receive a scoped passage rewrite with a measured word
target and retained evidence quotations. Overlong choices receive a batched rewrite
of only the failed choices, requesting 2–3 concise alternatives per choice. Python
selects a distinct alternative that fits the 55-character limit; an overlong first
candidate does not reject a valid later alternative. No text is padded or silently truncated. Valid units
need no extra repair calls. Missing or paraphrased evidence triggers a scoped repair
of only the affected questions, with the passage frozen. Harmless quote typography
and whitespace differences are normalized; invented wording remains invalid.
Evidence repairs offer numbered exact, bounded source excerpts. Gemini returns a
small integer `evidence_index`; Python inserts the source quote. Long excerpt enums
are no longer duplicated in each question's schema. An evidence request rejected
with HTTP 400 gets one JSON-object-mode retry with the same content validators;
another rejection stops with the actual error. This fallback is limited to evidence
repairs, and does not treat every HTTP 400 as a temporary outage.
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
`GEMINI_TRANSPORT_BUDGET_SECONDS` deadline (default **240 seconds**) across them.
A new pool round does not restart that deadline. `GEMINI_CALL_BUDGET_SECONDS`
(default 240) and `GEMINI_REQUEST_TIMEOUT_SECONDS` (default 60) further bound an
individual facade/HTTP request. Existing Railway variables override these defaults.
The defaults leave time for four 60-second credential attempts; successful requests
finish immediately. If these variables are already set in Railway, update them to
240, 240 and 60 respectively to use the longer limits.
A successful HTTP response with invalid content starts a separate bounded content
repair budget; a provider outage does not consume a content-validation attempt.
Scoped repair failures retain their own stage and error. They are not reclassified
as a parent HTTP failure that regenerates the original passage and adds misleading
parent deadline errors. Provider-wide outages and exhausted quotas can still stop a run.
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
checks, not certified reading-level scores or external fact checking. Short accessibility rewrites
are expanded with additions to the corrected text rather than rewritten again; the complete passage
must still meet its grade word range. Bullying guidance distinguishes unsafe evidence-first reporting
from optional documentation after adult help, and expansion is checked for the same issues.
No AI image reviewer is used.
Before selling, review facts, question ambiguity, illustrations, and the final PDF yourself;
model review and local print checks cannot guarantee instructional accuracy or sales.

Workbook styling uses blue/gold accents, alternating question panels, numbered reading paragraphs,
and uncropped square illustrations (86mm for grades 3–4; 76mm for grades 5–6). To leave room for
larger illustrations and clearer paragraph spacing, passages use 220–280 words or 320–380 words
for grades 3–4 or 5–6 respectively. The opening paragraph sits beside the full square
illustration; remaining paragraphs use the full page width. Generic reading tips no
longer consume the illustration's adjacent column. If a QCM page overflows, Python
tries a two-row A–D choice layout before requesting content repair, preserving every
question, option, answer and minimum student font size. Fit errors identify whether
the reading or question page failed.
Product titles should describe the reading comprehension actually included. The text
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
the passage and other questions remain frozen.
The blind solve also checks whether the actual task assesses its declared reading
skill. Repairs retain the original skill as a curriculum objective, including when
a returned label drifts; the repaired task must still pass this independent check.
Ordinary mismatches allow two repair rounds
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

Literal recall mislabeled as inference, implausible distractors, skill mismatches and
missing valid choices trigger a fresh scoped question immediately. Rejected stems
cannot be reused for inference/skill/distractor defects. If bounded answer verification
still fails, one fresh reading and question set on the same planned topic is allowed.
Other completed units remain intact. This fresh unit receives the same content,
layout and independent answer checks. A second semantic failure stops publication;
provider outages do not trigger this unit replacement.

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

### Chronological event and reading-topic selectors

The web form has separate **From an event** and **From a reading topic** modes.
Events show their inclusive exact date or range, including the year, and sort by
their current or next configured occurrence rather than alphabetically. Current
periods appear first; dates after New Year use the following year. Seasonal themes
are labeled **Teaching window**, so they are not mistaken for holiday dates.
The reference date follows `BOOK_TIMEZONE`, just like the daily picker.

Undated reading topics have their own subject-grouped list. It includes science,
nature, digital citizenship, media literacy, money choices, teamwork, accessibility,
history and reading skills. Select a topic and a grade, then click **Generate workbook**.
The existing `POST /generate` and `/generation-jobs` endpoints accept the selected
name in the `event` field for either list. Both use the same reading/QCM pipeline.
Schedules with no upcoming configured date appear under **Dates not configured**;
the app does not invent a date. Disabled events stay unavailable.

The daily cron still randomly selects one event overlapping days **7–37 ahead**,
ignoring the first week, with the existing seasonal/evergreen fallback.
Manual browsing order does not change that random selection. Added evergreen
topics are also available to that fallback when no eligible scheduled event exists.

### Choose the workbook type

The web generator offers two separate formats for either grade band (3–4 or 5–6),
and works with a link, description, event or undated reading topic:

- **Reading passages + QCM** (`reading_qcm`, default): the existing five illustrated
  reading/comprehension pairs. Its content and layout pipeline stays unchanged.
- **Mixed exercises — Gemini design** (`varied_activities`): Gemini plans ten
  activities and authors each page's HTML/CSS composition, palette and panels.
  Plans must include at least five different student actions and at least half
  contextual authored activities. Possible tasks include short-text comparison,
  vocabulary, process sequencing, table interpretation, applied math, writing,
  investigations and design challenges, selected for the topic and grade.

Both produce 12-page A4 PDFs: a cover with the real store logo, ten student pages
and one final answer key. Mixed mode preserves Gemini's page compositions instead
of replacing them with the legacy canonical worksheet layout. Python still binds
questions and answers from one shared specification, checks arithmetic and print
bounds, renders exact diagrams when needed, and assembles the PDF with WeasyPrint.
Cloudflare supplies illustration assets. Gemini image review remains disabled.
The content review checks for unsolvable tasks, incorrect keys, repeated activities,
cultural generalizations and fabricated primary sources. Invented source excerpts
and scenarios must explicitly be labeled fictional. Human review before sale is
still needed; automated checks cannot guarantee factual or instructional accuracy.

Select **Book type**, choose your grade and input, then click **Generate workbook**.
The library displays the selected type beside new books. Existing books remain
accessible. No new credentials, environment variables or deployment services are
needed. The daily cron continues to generate reading/QCM books.

Both POST endpoints accept an optional `book_type` field. For example:

```json
{
  "event": "The Solar System",
  "grade_band": "5th-6th",
  "book_type": "varied_activities"
}
```

Omitting `book_type` selects `reading_qcm`; unknown values return HTTP 400 before
generation starts.

Mixed-workbook authored tables have a separate allowance for **36 short headers/data
cells**, in addition to 24 short contextual captions and eight diagram identifiers.
This is a content cap, not permission to overflow an A4 page. Gemini's schema and
prompts use the same allowance. Declare IDs without the `caption_` prefix (for
example `row1_c1`) and bind them with `data-content="caption_row1_c1"`.
Python can bind complete literal cell text to a missing caption and preserve
repeated headers with distinct IDs. It does not invent values for empty unknown
slots, turn directions into data, or relax the ordinary prose-caption limit.
Reading/QCM books and exact puzzle caption limits stay unchanged.

Mixed authored activities allow up to 24 short contextual captions, plus the
separate table-cell allowance and eight diagram identifiers. The schema, content
compiler and layout-only repairs share these limits. Exact puzzles retain the
original six-caption rule. Pure underscore writing lines are preserved as blank
workspace; actual prompts, instructions and answers still require canonical fields.
Student font sizes and one-page print-bound checks remain enforced.

Mixed authored pages support `exercise.stimuli`: up to eight short source excerpts
or scenario blocks (`id`, `text`), each at most 650 characters, printed once in
`data-content="stimulus_ID"` slots. Existing long caption text is migrated without
truncation; short captions remain labels. These sources share a per-page planning
budget of about 90 words for grades 3–4 or 120 words for grades 5–6, leaving room
for substantial artwork and one or two focused responses. This does not impose
new passage limits on reading/QCM books.

If a mixed source-heavy page overflows and exceeds that planning word budget,
the bounded retry requests a complete content/layout revision instead of freezing
all long source text in a layout-only loop. It must retain facts and quantities
needed by the questions and realign shared answers; content proofreading still
runs before publication. Smaller source pages retain normal layout-only repair.
Fonts, response spaces, purposeful visual area and print bounds are still checked.

Mixed student pages automatically remove fixed height clamps from text containers
and redundant wrappers so wrapped source text cannot collide with the next task.
Artwork dimensions, canonical answer-box heights and empty/underscore-only work
panels are retained. Every reflowed page still has to pass one-page geometry,
overlap, student-font and visual-area checks. This reflow is opt-in for mixed
activities; the reading/QCM layout and cover remain unchanged.

Mixed layout-only retries keep original caption wording even if the model supplies
shorter caption suggestions. The returned HTML is re-bound to the original shared
content. Changing source content is still handled separately by a content revision
and its subsequent proofreading, never silently by a layout repair.

Mixed page recovery now carries the real grade configuration, caption allowances,
source blocks and planned title into local print-fit checks. Source/heading order
is retained, and real data tables are excluded from generic stacked recovery so
row/column associations cannot be lost. Any recovery candidate must pass both the
page geometry and meaningful artwork-area checks with all questions, answers and
response spaces intact. New mixed activities plan at most two focused tasks per
page; the reading/QCM question count and daily cron remain unchanged.

For mixed source-heavy pages, recovery first tries a sizeable square illustration
beside source text, avoiding a shallow panoramic placeholder for square artwork.
It uses the same source/caption allowances and grade limits as initial validation.
Every candidate is actually rendered and must satisfy both the visual-area floor
and one-page fit before it can be accepted.

Complete canonical instructions inside colored, bordered or padded text wrappers
are bound locally instead of requesting another Gemini layout. This normalization
requires the entire container to match the shared exercise wording. Additional
instructions, graphics, dimensioned panels and blank writing boxes remain protected
and cannot be discarded as formatting.

When complete canonical wording is immediately followed by an image, an explicit
content slot or a blank writing panel in the same wrapper, only that leading text
is bound into a separate slot. The following elements retain their original
attributes and pass normal asset, content and print checks. Partial or ambiguous
copies and question prefixes are not recovered this way; question response areas
remain owned by the shared question specification.

Standalone “Activity Goal:” and “Goal:” labels bind locally as contextual headings
within the existing caption budget. Their following wording still needs a declared
exercise field. Arithmetic word problems require a calculation for the complete
asked result; focused calculation/answer repairs retain the original prompt,
other tasks, artwork and response space.

Claim/record identifiers and short visitor-claim/measurement headings bind locally
without swallowing their content. Semantic text matching belongs in authored
activities with explicit source cards and an answer key; computed matching supports
only pictures and shadows. For an otherwise valid exact page, Python can resize the
existing SVG from its true smallest label size while preserving the original layout
and writing panels. The candidate still passes full page-fit and visual-area checks.

On computed puzzle pages, empty unused directions/passage placeholders are omitted
only when they contain no wording, graphics or sized/bordered writing panels.
Complete factual intro captions may be split into canonical caption chunks while
preserving every word and the existing caption budget. A heading such as “Activity
Sorting Task” can bind as context only when it matches the selected computed tool.
All recovered pages still pass geometry and readable-diagram-label checks.

Gemini cooldowns retain their cause between requests: a follow-up call during a
503 cooldown remains retryable within the existing request deadline. Quota and
authentication exhaustion do not become outage retries. This avoids premature
failure when another request has already cooled down all slots; it cannot resolve
a continuing provider outage or restore exhausted quota.

Mixed workbooks use the same configured 24-context-label allowance on authored
pages and computed exact pages, plus up to eight diagram identifiers. The initial
response schema, caption splitting, binding repairs and local diagram recovery
share this allowance and the real grade profile. The legacy exact profile still
uses six contextual labels. These are ceilings, not targets: every page must retain
readable fonts, valid exercise content and a measured one-page fit.

Exact-page recovery can restore missing standalone factual caption slots when the
complete wording already exists in the shared exercise. It cannot invent missing
tasks or guess where diagram identifiers such as Node A belong. Restored context
is compiled and print-checked with the unchanged puzzle, answers and response areas.
Diagram readability feedback now includes the current smallest printed label and
the physical dimensions required by that same diagram. Local exact recovery may
use up to 180mm of the 186mm printable width, subject to the usual geometry checks.

Blank bracket controls such as `[   ]` are treated as student workspace, not
independent exercise wording. Combined blank Name/Date lines are split into
canonical metadata fields with spacing and duplicate blank fields removed.
Filled values and appended tasks are not accepted as blank metadata. On an exact
page, an empty styled directions/passage box retains its geometry after detaching
the unused text binding; a nonempty mislabeled slot can rebind only to one exact
declared caption copy. Other instructions still need a coherent content repair.

Short standalone tip headings, including “Tip for Investigators:” and “Tip for
Young Readers:”, bind locally as contextual captions. Only the complete heading
is eligible: wording after the colon must still belong to a canonical exercise
field. Existing caption ceilings, tasks, answers, artwork and print checks remain
in effect, avoiding a model repair just to register a harmless heading.

Source-card capacity is shared by the response schema and Python validation:
production mixed pages allow eight short cards, while an explicitly configured
four-card profile retains four. A referenced source missing from the manifest
requires a complete source-manifest repair rather than an HTML-only correction.
The repair supplies missing text while Python retains all existing sources,
directions, questions, answers and images. Empty or duplicate missing-source entries
are rejected. The same combined word budget and single-page geometry still apply.
Blank writing lines may include literal table separators (`___________ |`), with
no independent words, numeric answers or instructions hidden in those separators.

Arithmetic answer parsing accepts ordinary sentence punctuation after whole
numbers, decimals, fractions, mixed numbers and grouped thousands. A decimal or
fraction cannot satisfy a check merely because its integer prefix matches the
expected answer. An unambiguous whole printed calculation can supply its missing
calculation metadata locally; its prose key still requires verification. Python
does not infer formulas from word-problem fragments or invent numeric prose answers.
