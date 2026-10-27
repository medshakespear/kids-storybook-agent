# Run the workbook agent on your Windows computer

The full web interface runs at **http://localhost:8080**. Choose a reference link,
description, calendar event or reading topic; select grades 3–4 or 5–6 and either
reading/QCM or simple varied exercises. Completed PDFs appear in the book library.
Railway is not required. Gemini/Cloudflare generation still needs internet access
and your API credentials; running locally does not remove provider quotas.

## First setup

1. Install and open [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
   Use its WSL 2/Linux containers option. Follow Docker's installer if it asks for
   WSL or virtualization to be enabled, and restart Windows if requested. Use a
   current Docker Desktop with Docker Compose 2.30 or newer.
2. Download this repository from GitHub with **Code → Download ZIP** and extract
   the entire folder to a permanent location such as `Documents\ClassroomAgent`.
   Git and Python do not need to be installed separately for this setup.
3. Double-click **Start Local.cmd**. On the first run, Notepad opens `.env.local`.
   Fill at least these three values, without quotes:

   ```dotenv
   GEMINI_API_KEY_1=your-own-Gemini-key
   CLOUDFLARE_API_TOKEN_1=your-own-Workers-AI-token
   CLOUDFLARE_ACCOUNT_ID=your-32-character-Cloudflare-account-ID
   ```

   The account ID is separate from the API token. Optional slots 2–4 are already
   listed in the file. Save, close Notepad, and press Enter in the launcher window.
   If tokens use different accounts, fill each corresponding
   `CLOUDFLARE_ACCOUNT_ID_N`. Save and close Notepad. Keep these values on your
   computer; never paste them into GitHub, screenshots or chat. The file is ignored
   by Git and excluded from the Docker image. The launcher validates settings
   locally; it does not spend AI credits to test them.
4. Wait for the first Docker build (it downloads Python, libraries and fonts).
   The launcher opens **http://localhost:8080** once the web service responds.

If your previous Railway model variable differed from the code default, copy its
model ID into `GEMINI_TEXT_MODEL` in `.env.local`. A provider 404 means that model
or endpoint is unavailable to your account; the launcher cannot prove API access
without a live request. Existing credential rotation and bounded retries remain.

## Daily use

- **Start Local.cmd** starts/updates the container and opens the interface.
- **Stop Local.cmd** stops it; saved files remain. Wait for active generation to
  finish first. Closing the browser does not stop generation.
- **View Logs.cmd** shows recent/live logs. Press Ctrl+C to stop viewing logs.
- **Run daily batch** in the web interface uses the calendar rotation and
  `DAILY_BOOK_COUNT` (default **1**). It shares the queue with on-demand jobs.
- Set `LOCAL_PORT=8081` if 8080 is busy, and rerun Start Local.cmd. Open the port
  shown by the launcher. The service binds to 127.0.0.1, not your public network.

Keep Docker Desktop running. Windows sleep/shutdown suspends/stops the agent;
it cannot generate books while the computer is off. Pending/running job status
is memory-only; interrupted work is not resumed after a restart. Completed PDFs
are retained. Start Local.cmd rebuilds from the files you downloaded; it does not
silently download a new repository version.

## Optional automatic daily generation

Edit `.env.local`, then run Start Local.cmd again:

```dotenv
LOCAL_AUTO_DAILY=1
LOCAL_DAILY_TIME=09:00
BOOK_TIMEZONE=Africa/Casablanca
DAILY_BOOK_COUNT=1
```

The single local web process checks every 30 seconds and queues one daily attempt
after that time. A late startup runs today's due batch; missed earlier dates are
not backfilled. An attempt marker is written to `state.json` before generation,
so a failed/interrupted scheduled batch will not automatically spend more API
requests that day. You can retry manually with **Run daily batch**. Set
`LOCAL_AUTO_DAILY=0` to disable the schedule. Avoid running a separate cron
container/process against this same data directory: the local entry point keeps
web and daily state writes in one serialized process.

## Files, backups and recovery

- `local-data/output/`: PDFs on your Windows disk.
- `local-data/state.json`: completed-book history, theme/grade rotation and the
  local daily-attempt marker. This is the only persistent application state file.
- `.env.local`: credentials and settings, stored separately from application state.

Back up `local-data` after stopping the service. For a complete move, also securely
back up `.env.local`. Rebuilding/stopping the container does not delete the host
folder. An empty installation starts fresh; it cannot recover files that existed
only on a deleted Railway volume. Copy any PDFs you already downloaded into
`local-data/output`; the library discovers them even without their old state.
To restore full old metadata, restore the matching `state.json` backup while the
service is stopped. Do not overwrite current state with an unrelated older file.

## Command-line equivalents

From the extracted repository directory:

```powershell
docker compose --env-file .env.local -f compose.local.yaml up -d --build
docker compose --env-file .env.local -f compose.local.yaml logs --tail 150 -f web
docker compose --env-file .env.local -f compose.local.yaml stop
```

After editing credentials, run Start Local.cmd again to recreate the container
with the new environment. No GitHub write-back token, Railway token, delivery URL
or database is needed. Local Compose explicitly disables remote delivery and
GitHub write-back. Your existing cover logo, calendar, web form and download
routes are reused.
