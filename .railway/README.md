# Railway infrastructure

This directory contains the project-level Railway Infrastructure as Code definition.
It creates two services from the same GitHub repository:

- `storybook-web`: an always-on Flask/Gunicorn service with `/health`, `/generate`, and PDF download routes.
- `storybook-daily-cron`: a job scheduled for `07:00 UTC` every day that runs `python cron_job.py` and exits.

Preview and apply it with Railway CLI 5.42.1 or later:

```bash
npm install
railway login
railway link
railway config plan
railway config apply
```

The `preserve()` entries expect their secret values to be entered in Railway before
the first apply. See the root `README.md` for the full deployment sequence.

