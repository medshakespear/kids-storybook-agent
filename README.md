# Book library update — manual Railway setup

Open `/` or `/books` on the web service to see titles, themes, grade bands, dates,
and PDF downloads. `/api/books` provides the same catalog as JSON. This page and
its downloads are public to anyone with the address. No generation history can be
inferred from a healthy deployment alone; the empty page means no stored books yet.

1. On the Railway project canvas, create a Volume, attach it to **web**, and set
   its mount path to `/data`. Set `DATA_DIR=/data` on web. Keep one replica and one
   Gunicorn worker (threads are supported).
2. On **web**, set `DELIVERY_TOKEN` to a long random password you choose. This is
   a shared application password, not an API subscription. Set the provider credentials listed below.
3. On **cron**, set `BOOK_LIBRARY_URL` to the web service's HTTPS base URL (no
   `/books` suffix), and set the same `DELIVERY_TOKEN`. Set the provider credentials listed below.
4. Web start command: `sh -c 'exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 900 webhook_server:app'`.
   Cron start command: `python cron_job.py`; schedule: `0 7 * * *`; restart: Never.
5. Redeploy both services. Run one cron test using `DAILY_BOOK_COUNT=1`, then remove
   that override for the normal 6–8 books. Look for `DELIVERED` in cron logs.
6. Open the web domain and refresh after completion. Each available book has a
   Download PDF button. On-demand books appear automatically too.

The web service stores PDFs at `/data/output` and all catalog/rotation data in
`/data/state.json`. No database or separate metadata files are introduced. Cron
reads that durable state before selecting themes and uploads each completed PDF
with metadata. Uploads are authenticated, bounded in size, and safe to retry.
A failed delivery is logged as a failed book and produces a nonzero job exit.
The remaining books still run. PDFs left only in a failed cron container require
manual recovery before the container disappears; there is no durable retry queue.

`GITHUB_TOKEN` is optional with volume-backed rotation. It is needed only if you
also want the original GitHub state-commit behavior. Only cron performs GitHub
write-back. Do not assume web and cron have a shared filesystem.

Old files in a replaced container cannot be recovered by this update. Copy any
existing PDFs into `/data/output` before removing their old storage. Files without
metadata appear under their filenames as recovered PDFs. Legacy history records
without PDFs are explicitly marked unavailable. Never wipe the volume to redeploy.

Existing `.railway/railway.ts` is optional CLI configuration; the manual volume and
transfer variables above must be configured separately. The dashboard persists
through restarts only after the volume is attached.

---

# Automated Kids Storybook Agent

A production-oriented Python agent that creates original, grade-scaled, illustrated
children's storybooks as printable A4 PDFs. Gemini (with optional Groq fallback) generates the structured story and Cloudflare generates
one illustration per page; WeasyPrint lays out the title, art, and readable text bands.
There is no Canva integration, database, or scraper. OpenAI remains an explicit opt-in backend.

## What it does

- **Daily cron:** chooses 6-8 books from school events occurring in the next 1-4 weeks,
  rotates coverage across four grade bands, avoids recently used theme/grade pairs,
  continues after individual failures, updates `state.json`, and commits that state back
  to GitHub when repository credentials are configured.
- **On-demand webhook:** accepts one reference URL plus an optional grade band, derives
  a broad niche seed from URL/slug words without visiting the page, and creates one
  original book. The prompt explicitly forbids copying wording, structure, characters,
  branding, trade dress, or visual identity.
- **PDF output:** writes files as
  `output/YYYY-MM-DD_grade-band_story-title.pdf`. Each PDF has an A4 portrait title page
  followed by a full-page illustration and a grade-appropriate text treatment per page.

## Repository layout

```text
.
├── .railway/railway.ts       # Current Railway IaC: web + cron services
├── calendar.json             # Full-year US school event calendar
├── grade_config.json         # Reading/layout/art settings by grade band
├── state.json                # The only persistent generation state
├── core/
│   ├── image_generator.py
│   ├── pdf_builder.py
│   ├── pipeline.py
│   ├── state_manager.py
│   ├── story_generator.py
│   └── theme_picker.py
├── cron_job.py               # Daily batch entry point
├── webhook_server.py         # Flask webhook and PDF download service
├── Dockerfile                # Python 3.11 + WeasyPrint native libraries
├── Procfile
└── requirements.txt
```

## Configuration

### Required

Set these variables on **both Railway services** (web and cron):

| Variable | Value |
| --- | --- |
| `TEXT_PROVIDER` | `gemini` (default) |
| `IMAGE_PROVIDER` | `cloudflare` (default) |
| `GEMINI_API_KEY` | Your Google AI Studio API key |
| `CLOUDFLARE_API_TOKEN` | Workers AI token with permission to run models |
| `CLOUDFLARE_ACCOUNT_ID` | Your 32-character Cloudflare account ID |
| `GROQ_API_KEY` | Optional; enables Groq story fallback |

The default text model is `GEMINI_TEXT_MODEL=gemini-2.5-flash-lite`.
Groq uses `GROQ_TEXT_MODEL=llama-3.3-70b-versatile`. Override model IDs when
provider availability changes. `TEXT_FALLBACK_PROVIDER=none` disables fallback;
otherwise Groq is enabled when its key is present. `TEXT_PROVIDER=groq` can also
use Groq directly without a Gemini key.

Images use Cloudflare `@cf/black-forest-labs/flux-1-schnell` with
`CLOUDFLARE_IMAGE_STEPS=4` (allowed 1–8). The endpoint controls output dimensions;
the code does not send unsupported width/height parameters. Square illustrations
are cropped by the existing A4 layout. Inspect character consistency and print
sharpness before selling PDFs. JPEG responses are validated and converted to PNG.

No OpenAI key is required with these defaults, even if an old key remains in Railway.
For paid OpenAI explicitly set `TEXT_PROVIDER=openai` and/or `IMAGE_PROVIDER=openai`
and `OPENAI_API_KEY`. Existing `OPENAI_TEXT_MODEL`, `OPENAI_IMAGE_MODEL`, and
`OPENAI_IMAGE_QUALITY` overrides still work. The `openai` Python package is also the
compatible HTTP client for Gemini/Groq; its presence does not mean calls go to OpenAI.

Free provider quotas are account-specific and can change; the app does not guarantee
free or unlimited production. Use free-tier accounts to avoid usage billing. It
retries transient failures with bounded backoff, then tries the configured text
fallback. Authentication errors fail immediately for that provider. Image failures
fail that book; cron continues remaining books. There is no automatic paid fallback
or automatic next-day resume. API keys and provider response bodies are not logged.

After saving variables, deploy the latest GitHub commit on both services. Set
`DAILY_BOOK_COUNT=1` on cron for the first run; check `/books` after a successful
delivery, then increase the count. Keep your existing volume, `DATA_DIR`,
`BOOK_LIBRARY_URL`, and `DELIVERY_TOKEN` settings.

### Optional GitHub state write-back

Railway's build checkout does not expose a reusable GitHub write credential. To fulfill
the state-commit requirement, set these variables on the cron service:

- `GITHUB_TOKEN`: a fine-grained token for this repository with **Contents: Read and write**.
- `GITHUB_REPOSITORY=medshakespear/kids-storybook-agent`
- `GITHUB_BRANCH=main` (optional; defaults to `main`).

The job updates `state.json` atomically after every successful book, then makes one GitHub
Contents API commit at the end. If the token is absent, generation still completes and a
clear state-persistence warning is printed, but the next Railway container will not retain
that local state. With library delivery configured, cron instead reloads current
rotation state from the web service volume at the start of each run.

### Optional

- `WEBHOOK_API_KEY`: when set, clients must send the same value in `X-API-Key`.
- `DAILY_BOOK_COUNT`: fixed batch size from 1-20; unset means a random 6-8.
- `LOG_LEVEL`: Flask logging level, default `INFO`.
- `PORT`: local web port, default `8080`; Railway supplies this automatically.

## Run locally

Python 3.11+ is required. WeasyPrint also requires its native libraries; the included
Dockerfile is the most reproducible option.

### Docker

```bash
docker build -t kids-storybook-agent .
docker run --rm -p 8080:8080 -e GEMINI_API_KEY -e CLOUDFLARE_API_TOKEN -e CLOUDFLARE_ACCOUNT_ID kids-storybook-agent
```

Open `http://localhost:8080/health` to verify the web service.

### Local Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="your-gemini-key"
export CLOUDFLARE_API_TOKEN="your-cloudflare-token"
export CLOUDFLARE_ACCOUNT_ID="your-cloudflare-account-id"
python webhook_server.py
```

Run a daily batch manually:

```bash
DAILY_BOOK_COUNT=1 python cron_job.py
```

Run the test suite without making external API calls:

```bash
python -m unittest discover -s tests -v
```

## Webhook API

### `POST /generate`

Request:

```json
{
  "link": "https://www.teacherspayteachers.com/Product/Data-Collection-Sheets-for-Special-Education-IEP-Goals-EDITABLE-7823047",
  "grade_band": "3rd-4th"
}
```

Allowed grade bands are `Pre-K-K`, `1st-2nd`, `3rd-4th`, and `5th-6th`. If omitted, the
service selects the least recently represented band from the current read-only state.

Example request:

```bash
curl -X POST "http://localhost:8080/generate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: optional-webhook-secret" \
  -d '{"link":"https://www.teacherspayteachers.com/Product/Data-Collection-Sheets-for-Special-Education-IEP-Goals-EDITABLE-7823047","grade_band":"3rd-4th"}'
```

Successful response:

```json
{
  "status": "completed",
  "title": "Mina and the Pattern Parade",
  "grade_band": "3rd-4th",
  "pdf_path": "/output/2026-09-22_3rd-4th_mina-and-the-pattern-parade.pdf",
  "download_url": "https://your-service.up.railway.app/output/2026-09-22_3rd-4th_mina-and-the-pattern-parade.pdf"
}
```

Generation is synchronous and can take several minutes because every page receives a
separate image request. Gunicorn's timeout is set to 15 minutes. PDFs persist on the
web service's `/data` volume when configured as described at the top of this README.
Without that volume, files are ephemeral and can disappear on redeployment.

## Railway deployment through the website

Use the manual setup at the top of this README. Connect this GitHub repository to
**two services** in the same Railway project:

| Service | Start command | Schedule |
| --- | --- | --- |
| web | `sh -c 'exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 900 webhook_server:app'` | Always on |
| cron | `python cron_job.py` | `0 7 * * *` (07:00 UTC daily) |

Set the provider variables in both services, attach the volume to web, and set the
cron delivery variables. In the web service's networking settings, generate a public
domain. Your library is `https://your-domain/books`, webhook is
`https://your-domain/generate`, and health check is `https://your-domain/health`.
Set cron's restart policy to Never. Redeploy both services after changing variables.
No Railway CLI is needed. The optional `.railway/railway.ts` is for CLI users only.

## Operational notes

- A 6-8 book batch may make 70+ image calls, so monitor provider quotas and costs.
- API and validation failures use bounded exponential backoff. One failed daily book does
  not stop the rest of the batch.
- Character descriptions are inserted verbatim into every page prompt after validation,
  while a fixed style-lock keeps palette, rendering, and proportions consistent.
- Image models do not guarantee perfect recurring-character identity. The prompt strategy
  improves consistency without claiming deterministic identity preservation.
- Review every generated PDF for accuracy, age appropriateness, layout, and commercial
  licensing/policy compliance before listing it on Teachers Pay Teachers.

