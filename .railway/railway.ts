import {
  defineRailway,
  github,
  preserve,
  project,
  service,
} from "railway/iac";

const repository = "medshakespear/kids-storybook-agent";

export default defineRailway(() => {
  const web = service("storybook-web", {
    source: github(repository, { branch: "main" }),
    start:
      "sh -c 'exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 900 webhook_server:app'",
    healthcheck: "/health",
    healthcheckTimeout: 300,
    env: {
      GEMINI_API_KEY: preserve(),
      GROQ_API_KEY: preserve(),
      TEXT_PROVIDER: "gemini",
      IMAGE_PROVIDER: "cloudflare",
      CLOUDFLARE_ACCOUNT_ID: preserve(),
      CLOUDFLARE_API_TOKEN: preserve(),
      BOOK_TIMEZONE: "UTC",
      GEMINI_TEXT_MODEL: "gemini-3.5-flash-lite",
    },
    deploy: {
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 5,
    },
  });

  const dailyCron = service("storybook-daily-cron", {
    source: github(repository, { branch: "main" }),
    start: "python cron_job.py",
    env: {
      GEMINI_API_KEY: preserve(),
      GROQ_API_KEY: preserve(),
      TEXT_PROVIDER: "gemini",
      IMAGE_PROVIDER: "cloudflare",
      CLOUDFLARE_ACCOUNT_ID: preserve(),
      CLOUDFLARE_API_TOKEN: preserve(),
      BOOK_TIMEZONE: "UTC",
      GITHUB_TOKEN: preserve(),
      GITHUB_REPOSITORY: repository,
      GITHUB_BRANCH: "main",
      GEMINI_TEXT_MODEL: "gemini-3.5-flash-lite",
    },
    deploy: {
      cronSchedule: "0 7 * * *",
      restartPolicyType: "NEVER",
    },
  });

  return project("kids-storybook-agent", {
    resources: [web, dailyCron],
  });
});
