# Conventions for Claude working on this repo

Moodle Study Companion: self-hosted, single-user. FastAPI backend + (from M2) React/Vite PWA,
served from one image behind Caddy via Docker Compose. The build plan (project knowledge) is
the source of truth; work one milestone at a time and open one PR per milestone.

## Hard rules

- **No LLM API calls** anywhere in the app. AI happens in the Claude apps via the MCP connector.
- **Secrets only via environment variables** (`app/config.py`). Never log tokens, passwords,
  or URLs that contain tokens (Moodle `fileurl` + `token=`). Keep secrets out of `repr`.
- **Tests never call a real Moodle.** Every Moodle API call gets a pytest test with recorded or
  mock JSON. Handle missing fields defensively; Moodle versions differ.
- **Rate-limit Moodle requests** (about 2 req/s) and back off on errors.
- **Sanitise file and folder names** from Moodle: no path traversal, max ~200 characters.
- The app listens only inside Docker (no published ports); Caddy terminates HTTPS.
- MCP tools return compact, paginated text with file and page references; `read_file` takes a
  page range. The MCP server must work as a claude.ai custom connector (streamable HTTP,
  OAuth 2.1 with discovery, dynamic client registration, PKCE).
- Prompt templates are Markdown in `backend/app/prompts/` and must reference real MCP tool names.
- The web UI must work on a phone screen.
- **Ask before adding dependencies or services** beyond the plan.
- Keep `README.md` and `docs/` current (VPS setup, domain/HTTPS, backups, connector guide).

## Layout

- `backend/app/main.py` app factory (`create_app(settings)`; uvicorn uses `get_app --factory`)
- `backend/app/config.py` `Settings.from_env()`; validates required secrets at startup
- `backend/app/auth/` UI password login (signed cookie, login throttle); OAuth for MCP in M3
- `backend/tests/` pytest; `conftest.py` builds an app with test settings
- `docker/Dockerfile`, `docker-compose.yml`, `deploy/Caddyfile`, `.env.example`
- `.github/workflows/ci.yml` (tests, compose/Caddyfile validation, image smoke test),
  `release.yml` (tag `vX.Y.Z` -> GHCR multi-arch image + GitHub Release)

## Workflow

- `cd backend && pip install -e ".[dev]" && pytest` before every push.
- Small commits with clear messages.
- Version lives in `backend/app/__init__.py`; the release tag must match it.
