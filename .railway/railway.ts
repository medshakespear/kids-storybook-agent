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
      OPENAI_API_KEY: preserve(),
      OPENAI_TEXT_MODEL: "gpt-4.1-mini",
      OPENAI_IMAGE_MODEL: "gpt-image-1",
      OPENAI_IMAGE_QUALITY: "medium",
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
      OPENAI_API_KEY: preserve(),
      GITHUB_TOKEN: preserve(),
      GITHUB_REPOSITORY: repository,
      GITHUB_BRANCH: "main",
      OPENAI_TEXT_MODEL: "gpt-4.1-mini",
      OPENAI_IMAGE_MODEL: "gpt-image-1",
      OPENAI_IMAGE_QUALITY: "medium",
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
