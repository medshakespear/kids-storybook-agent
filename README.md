# Automated Kids Storybook Agent

A production-oriented Python agent that creates original, grade-scaled, illustrated
children's storybooks as printable A4 PDFs. OpenAI generates the structured story and
one illustration per page; WeasyPrint lays out the title, art, and readable text bands.
There is no Canva integration, database, scraper, or non-OpenAI AI service.

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

Set `OPENAI_API_KEY` for both processes. The default models are:

- `OPENAI_TEXT_MODEL=gpt-4.1-mini`
- `OPENAI_IMAGE_MODEL=gpt-image-1`
- `OPENAI_IMAGE_QUALITY=medium`

You can override any of those environment variables without changing code.

### Required for cron state persistence on Railway

Railway's build checkout does not expose a reusable GitHub write credential. To fulfill
the state-commit requirement, set these variables on the cron service:

- `GITHUB_TOKEN`: a fine-grained token for this repository with **Contents: Read and write**.
- `GITHUB_REPOSITORY=medshakespear/kids-storybook-agent`
- `GITHUB_BRANCH=main` (optional; defaults to `main`).

The job updates `state.json` atomically after every successful book, then makes one GitHub
Contents API commit at the end. If the token is absent, generation still completes and a
clear state-persistence warning is printed, but the next Railway container will not retain
that local state.

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
docker run --rm -p 8080:8080 -e OPENAI_API_KEY="your-key" kids-storybook-agent
```

Open `http://localhost:8080/health` to verify the web service.

### Local Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="your-key"
python webhook_server.py
```

Run a daily batch manually:

```bash
OPENAI_API_KEY="your-key" DAILY_BOOK_COUNT=1 python cron_job.py
```

Run the test suite without making OpenAI calls:

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
separate image request. Gunicorn's timeout is set to 15 minutes. Generated webhook PDFs
are on Railway's ephemeral filesystem; download them before a redeploy/restart, or attach
a Railway volume at `/app/output` if long-term PDF storage is needed. A volume is file
storage, not a database, and `state.json` remains the only application state record.

## Railway deployment

Railway replaced per-service `railway.json` configuration with project-level
Infrastructure as Code in 2026. The current `.railway/railway.ts` is the modern equivalent
and defines both required services from this repository:

| Service | Process | Schedule |
|---|---|---|
| `storybook-web` | Gunicorn serving `webhook_server:app` | Always on |
| `storybook-daily-cron` | `python cron_job.py` | `0 7 * * *` (07:00 UTC daily) |

1. Install Railway CLI 5.42.1 or newer and Node 22+.
2. Clone this repository and run `npm install` (installs the Railway IaC SDK only).
3. Run `railway login`, then `railway init` to create/link a project.
4. In Railway, create the shared/secret values expected by `preserve()`:
   `OPENAI_API_KEY` for both services and `GITHUB_TOKEN` for the cron service. You may
   initially create the two service variables after the first plan identifies the services.
5. Preview changes with `railway config plan`; review that it creates exactly the two
   services above. Apply with `railway config apply`.
6. In the `storybook-web` service, open **Settings > Networking** and choose
   **Generate Domain**. Railway will display the public base URL. Your webhook is
   `https://that-domain/generate`, and health is `https://that-domain/health`.

Railway evaluates cron schedules in UTC. Change `cronSchedule` in
`.railway/railway.ts` if another UTC time is preferable, then run plan/apply again.

Official Railway references:

- [Infrastructure as Code](https://docs.railway.com/infrastructure-as-code)
- [Cron jobs](https://docs.railway.com/cron-jobs)
- [Public networking](https://docs.railway.com/networking/public-networking)

## Operational notes

- A 6-8 book batch may make 70+ image calls, so monitor OpenAI rate limits and cost.
- API and validation failures use bounded exponential backoff. One failed daily book does
  not stop the rest of the batch.
- Character descriptions are inserted verbatim into every page prompt after validation,
  while a fixed style-lock keeps palette, rendering, and proportions consistent.
- Image models do not guarantee perfect recurring-character identity. The prompt strategy
  improves consistency without claiming deterministic identity preservation.
- Review every generated PDF for accuracy, age appropriateness, layout, and commercial
  licensing/policy compliance before listing it on Teachers Pay Teachers.

