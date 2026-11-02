# Study Companion

A self-hosted, single-user study companion. It syncs your Moodle courses, shows what is due,
and exposes your course material to Claude (phone, desktop and web) through a remote MCP
connector, so Claude can tutor you, summarise sections and quiz you. The app itself makes no
LLM API calls; all AI work happens in the Claude apps on your subscription.

It runs as two containers (app + Caddy for automatic HTTPS) on a small VPS, for example an
Infomaniak VPS Lite in Geneva.

## Status

| Milestone | Scope | State |
| --- | --- | --- |
| M0 | Skeleton, password-protected hello page, Docker + Caddy, CI, release pipeline, server guide | ✅ this release |
| M1 | Moodle sync (courses, contents, files, deadlines), nightly backups | next |
| M2 | Web UI: dashboard, course view, calendar + ICS, phone layout | |
| M3 | MCP connector (OAuth 2.1), text extraction and search, prompt builder | |
| M4 | Study loop: Claude's notes and questions, flashcards, catch-up plan | |

## Install on a server

See **[docs/server-setup.md](docs/server-setup.md)**: order and harden the VPS, point a
domain at it, install Docker, then:

```bash
curl -fsSL https://github.com/tkint/study-companion/releases/latest/download/study-companion-deploy.tar.gz \
  | tar xz --strip-components=1
cp .env.example .env && chmod 600 .env   # fill in DOMAIN, APP_PASSWORD, SECRET_KEY
docker compose up -d
```

Update with `docker compose pull && docker compose up -d`.

## Configuration

All settings come from environment variables (`.env` on the server, never committed).

| Variable | Required | Description |
| --- | --- | --- |
| `DOMAIN` | yes | Public hostname, e.g. `study.yourname.ch`. Caddy gets its certificate. |
| `APP_PASSWORD` | yes | Web UI password, 12+ characters. |
| `SECRET_KEY` | yes | 32+ characters; `openssl rand -hex 32`. Rotating it signs you out. |
| `IMAGE_TAG` | no | Image version to run (default `latest`). |
| `MOODLE_URL`, `MOODLE_TOKEN` | from M1 | Moodle site and web service token. |
| `SESSION_MAX_AGE` | no | Session length in seconds (default 7 days). |
| `COOKIE_SECURE` | no | Default `true`; set `false` only for local plain-HTTP development. |

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

Full stack locally (Caddy issues a local certificate for `localhost`):

```bash
docker build -f docker/Dockerfile -t ghcr.io/tkint/study-companion:latest .
cp .env.example .env   # set DOMAIN=localhost, APP_PASSWORD, SECRET_KEY
docker compose up -d && curl -k https://localhost/healthz
```

## Releases

Push a tag `vX.Y.Z` matching `backend/app/__init__.py`; GitHub Actions tests, builds the
amd64/arm64 image to `ghcr.io/tkint/study-companion` and publishes a GitHub Release with
the deploy files. Details in [docs/releasing.md](docs/releasing.md).

## Repository layout

```
backend/app/        FastAPI app (config, auth; moodle, extract, planner, prompts, mcp in later milestones)
backend/tests/      pytest (Moodle responses always mocked)
deploy/Caddyfile    HTTPS reverse proxy
docker/Dockerfile   multi-stage image
docker-compose.yml  app + Caddy
docs/               server setup, releasing (backups and connector guide follow)
.github/workflows/  ci.yml, release.yml
```
