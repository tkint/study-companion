# Study Companion

A self-hosted, single-user study companion. It syncs your Moodle courses, shows what is due,
and exposes your course material to Claude (phone, desktop and web) through a remote MCP
connector, so Claude can tutor you, summarise sections and quiz you. The app itself makes no
LLM API calls; all AI work happens in the Claude apps on your subscription.

The app runs behind a shared Caddy for automatic HTTPS on a small VPS, for example an
Infomaniak VPS Lite in Geneva. Caddy lives in its own Compose project and can also serve
other applications on the same machine.

## Status

| Milestone | Scope | State |
| --- | --- | --- |
| M0 | Skeleton, password-protected hello page, Docker + Caddy, CI, release pipeline, server guide | ✅ v0.1.0 |
| M1 | Moodle sync (courses, contents, files, deadlines, course language), settings page, nightly backups | ✅ v0.2.x |
| M2 | Web UI: dashboard, course view with PDF viewer, calendar + ICS feed, installable on your phone | ✅ v0.3.0 |
| M3 | MCP connector (OAuth 2.1), text extraction and search, prompt builder | ✅ v0.4.0 |
| M4 | Study loop: Claude saves notes, questions and quiz results; flashcards with spaced repetition; rule-based catch-up plan | ✅ released |
| M5 | Polish: reminders (calendar alarms, daily study event, in-app card), study-time tracking, more prompt templates | ✅ this release |

## Install on a server

See **[docs/server-setup.md](docs/server-setup.md)**: order and harden the VPS, point a
domain at it and install Docker. Then set `DOMAIN`, `SECRET_KEY` and `APP_PASSWORD` in the
repository's `production` environment and run the **Deploy** workflow
([docs/releasing.md](docs/releasing.md#deploy-to-the-vps-from-github-manual)).

Then sign in at `https://<DOMAIN>`, open **Settings** and connect your Moodle:
**[docs/moodle-token.md](docs/moodle-token.md)** explains how to get the token with
university SSO. Set up nightly backups with **[docs/backups.md](docs/backups.md)**.
**[docs/web-ui.md](docs/web-ui.md)** covers the dashboard, adding the app to your phone's home
screen, subscribing to your deadlines from your phone or Outlook calendar, and the prompt
builder, Claude's notes, study mode (flashcards), study time, reminders, the catch-up plan and the timed study
schedule with its `.ics` export.
**[docs/connector.md](docs/connector.md)** adds the Claude connector on claude.ai
(`https://<DOMAIN>/mcp`), so Claude on your phone and computer can read your courses and save
its summaries, questions and quiz results back to the app.

Updates: run the **Deploy** workflow again (see [docs/releasing.md](docs/releasing.md)).

## Configuration

Server settings come from environment variables: on the server, the Deploy workflow writes
them to `.env` from the GitHub `production` environment (never committed).
Your Moodle site, token and the web UI password are managed on the **Settings** page and
stored in the database (token encrypted with `SECRET_KEY`, password hashed with scrypt), so
you never edit `.env` to change them.

| Variable | Required | Description |
| --- | --- | --- |
| `DOMAIN` | yes | Public hostname, e.g. `study-companion.ch`. Deployment renders it into the shared edge's site file. |
| `SECRET_KEY` | yes | 32+ characters; `openssl rand -hex 32`. Signs sessions and encrypts the Moodle token: rotating it signs you out and means pasting the token again. |
| `APP_PASSWORD` | first start | Initial web UI password, 12+ characters. Ignored once set; change it on the Settings page. |
| `IMAGE_TAG` | no | Image version to run (default `latest`). |
| `MOODLE_URL`, `MOODLE_TOKEN` | no | Optional pre-fill, imported once on the first start. `MOODLE_TOKEN` also accepts a `moodlemobile://token=…` link. |
| `SYNC_INTERVAL_HOURS` | no | Scheduled sync interval (default 6; `0` turns it off). |
| `MOODLE_MAX_FILE_MB` | no | Larger files (usually videos) are listed but not downloaded (default 200). |
| `MOODLE_RATE_LIMIT` | no | Moodle requests per second (default 2). |
| `SESSION_MAX_AGE` | no | Session length in seconds (default 7 days). |
| `COOKIE_SECURE` | no | Default `true`; set `false` only for local plain-HTTP development. |
| `TIMEZONE` | no | Time zone for dates in Claude's tools and prompts (default `Europe/Zurich`). |
| `OAUTH_REDIRECT_HOSTS` | no | Hosts the connector's OAuth may redirect to (default `claude.ai,claude.com,localhost,127.0.0.1`). Add Gemini's three `oauth-redirect*.googleusercontent.com` hosts or `chatgpt.com` for ChatGPT ([docs/connector.md](docs/connector.md)). |
| `OAUTH_ACCESS_TTL`, `OAUTH_REFRESH_TTL` | no | Connector token lifetimes in seconds (default 1 hour and 30 days). |

## Moodle sync

The sync runs every 6 hours, a couple of minutes after start-up, and when you press
**Sync now**. It stores courses (with their language: English, French, Spanish…), sections,
activities, completion and deadlines in SQLite, and downloads files to
`/data/courses/<course>/<NN section>/`, skipping files Moodle reports as unchanged. From the
server you can also run:

```bash
docker compose exec app python -m app.cli check   # test the saved token, list courses
docker compose exec app python -m app.cli sync    # full sync now, prints a summary
docker compose exec app python -m app.cli extract # redo text extraction (--force: every file)
```

After the downloads, the sync extracts text from PDF, PowerPoint, Word, HTML and text files
(page by page) and indexes it for full-text search, so Claude can read and search it.

## Development

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest

# Run locally on http://127.0.0.1:8000
APP_PASSWORD=dev-password-123 SECRET_KEY=$(openssl rand -hex 32) COOKIE_SECURE=false DATA_DIR=./data \
  uvicorn app.main:get_app --factory --reload
```

Web UI (React + Vite + TypeScript, Node 22): with the backend running on port 8000,

```bash
cd frontend
npm ci
npm run dev     # http://localhost:5173, proxies the API to :8000; sign in at /login
npm run build   # type-check + bundle into frontend/dist, which the backend then serves at /
```

Without a build, `/` shows the basic server-rendered status page (`/status` always does).

Full stack locally with the published image (Caddy issues a local certificate for `localhost`):

```bash
cp .env.example .env   # set DOMAIN=localhost, APP_PASSWORD, SECRET_KEY
python3 deploy/caddy/deploy.py . docker-compose.yml deploy/study-companion.caddy
curl -k https://localhost/healthz
```

## Releases

Push a tag `vX.Y.Z` (the tag is the version, nothing to bump in the code); GitHub Actions tests, builds the
amd64/arm64 image to `ghcr.io/tkint/study-companion` and publishes a GitHub Release with
the deploy files. Details in [docs/releasing.md](docs/releasing.md).

## Repository layout

```
backend/app/        FastAPI app: config, auth, accounts, models/db, moodle/ (client, sync,
                    scheduler), extract/ (text + FTS5 search), materials.py, mcp_tools.py +
                    mcp_server.py (/mcp), auth/oauth*.py (OAuth 2.1), prompts/ (templates),
                    study.py, study_time.py, reminders.py, planner/,
                    api/ (UI routes, ICS feed, prompt builder)
backend/tests/      pytest (Moodle responses always mocked)
frontend/           React + Vite PWA: dashboard, courses, PDF viewer (pdf.js), calendar (FullCalendar)
deploy/caddy/       shared Caddy (separate Compose project) and its deploy script
deploy/study-companion.caddy  this app's site, added to Caddy through its admin API
docker/Dockerfile   multi-stage image
docker-compose.yml  app only, on the shared `edge` network
deploy/backup.sh    nightly restic backup of the data volume
docs/               server setup, Moodle token, web UI, Claude connector, backups, releasing
.github/workflows/  ci.yml, release.yml
```
