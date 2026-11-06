# Conventions for Claude working on this repo

Study Companion: self-hosted, single-user. FastAPI backend + (from M2) React/Vite PWA,
served from one image behind Caddy via Docker Compose. The build plan (project knowledge) is
the source of truth; work one milestone at a time and open one PR per milestone.

## Hard rules

- **No LLM API calls** anywhere in the app. AI happens in the Claude apps via the MCP connector.
- **Server secrets via environment variables** (`app/config.py`). User credentials the user
  changes in the UI (Moodle URL/token, UI password) live in SQLite: the token encrypted with
  SECRET_KEY (`app/auth/crypto.py`), the password scrypt-hashed (`app/accounts.py`). Never log
  tokens, passwords, or URLs that contain tokens (Moodle `fileurl` + `token=`). Keep secrets
  out of `repr`.
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
- `backend/app/auth/` UI password login (signed cookie, login throttle), crypto helpers;
  `oauth.py` + `oauth_routes.py` OAuth 2.1 server for the connector (DCR, PKCE, refresh rotation)
- `backend/app/accounts.py` account + Moodle credentials (single user id 1, schema ready for more)
- `backend/app/models.py`, `db.py` SQLModel tables, SQLite engine, DB snapshot for backups
- `backend/app/moodle/` `client.py` (rate limit, backoff, redaction), `api.py` (one wrapper per
  web service function), `sync.py`, `scheduler.py`, `names.py` (safe paths), `text.py` (multilang, language)
- `backend/app/extract/` `formats.py` (PDF/DOCX/PPTX/HTML/text to pages), `index.py` (FileText/FilePage,
  FTS5 `search_index`, run after each sync)
- `backend/app/teacher_pages.py` Moodle page/book HTML (`index.html`): readable titles, allow-list
  sanitising, images/attachments resolved to synced files (`/api/files/{id}/page`); the UI renders it
  with `src/components/HtmlContent.tsx` (second allow-list, React elements, no innerHTML)
- `backend/app/materials.py` course read model (period -> sections) shared by MCP tools and prompts
- `backend/app/study.py` study loop: Claude's notes, questions (SM-2 spaced repetition), quiz results,
  sections marked studied, hours per day; `backend/app/planner/` rule-based catch-up plan, `planner/schedule.py`
  timed study schedule (capacity, unavailabilities, course weights, recall blocks; `ScheduleSettings`), `api/schedule.py`
  its API and `.ics` download (editor: `#/schedule`)
- `backend/app/study_time.py` study sessions (web timer, manual, Claude's `log_study_time`), totals, streak;
  `backend/app/reminders.py` reminder settings, deadline alarms + daily study event in the ICS feed, `/api/reminders`
- `backend/app/mcp_tools.py` read and write tools as plain text functions (`TOOL_NAMES`); `mcp_server.py`
  registers them with the official MCP SDK (stateless streamable HTTP, JSON) at `/mcp` behind the bearer check
- `backend/app/prompts/` Markdown templates (defaults) + builder (`__init__.py`); `store.py` your edits in
  SQLite (`PromptTemplateEdit`) and their validation; `api/prompts.py` its JSON API (editor: `#/templates`)
- `backend/app/api/` `routes.py` (UI JSON API, `/files/{id}`, `/calendar.ics`), `ui.py` (read
  models: dashboard, course detail, deadlines), `study.py` (notes, flashcards, results, plan API),
  `ics.py` (ICS + feed token), `status.py`
- `frontend/` React + Vite + TS PWA (hash routes in `src/router.ts`, API types in `src/api.ts`);
  `npm run build` -> `frontend/dist`, served by the backend (`FRONTEND_DIR` in the image).
  Navigation map in `src/nav.ts` (sections = tabs, their pages, page titles): a new page needs a line there.
  `components/SectionNav.tsx` shows a section's pages; `components/Tour.tsx` is the first-visit tour (`?` replays it).
  Login and settings stay server-rendered. Files from Moodle: only PDF/images/text inline.
  Claude's Markdown is rendered by `src/components/Markdown.tsx` into React elements (no innerHTML).
  Styling: styled-components only (no CSS files, no utility classes). Tokens in `src/styles/theme.ts`
  (colours resolve to CSS variables so the light/dark switch in `src/colorScheme.ts` needs no re-render),
  base styles in `src/styles/GlobalStyle.ts`, typed primitives in `src/ui/` (Button, Card, Badge,
  ProgressBar, Modal, Dropdown, form fields, layout). Transient `$props` for style-only props.
- `backend/app/cli.py` `python -m app.cli check|sync|snapshot-db`
- `deploy/backup.sh` restic backup of the data volume (docs/backups.md)
- `backend/tests/` pytest; `conftest.py` builds an app with test settings
- `docker/Dockerfile`, `docker-compose.yml` (app only), `.env.example`
- `deploy/caddy/` shared Caddy project and its admin-API deploy script, `deploy/study-companion.caddy` site
- `.github/workflows/ci.yml` (tests, compose/Caddyfile validation, image smoke test),
  `release.yml` (tag `vX.Y.Z` -> GHCR multi-arch image + GitHub Release)

## Workflow

- `cd backend && pip install -e ".[dev]" && pytest` and `cd frontend && npm ci && npm run build`
  before every push.
- Small commits with clear messages.
- Don't bump a version in code: the release tag `vX.Y.Z` is the version (passed to the image as
  `APP_VERSION`, read in `backend/app/__init__.py`; `dev` locally).
