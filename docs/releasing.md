# Releasing

Releases are fully automated from a version tag. The version is not stored in the code:
the tag is the version. Merge to `main` as usual, then:

1. Tag the commit to release (semantic versioning) and push the tag:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

2. `.github/workflows/release.yml` then:
   - runs the CI workflow (tests, compose/Caddyfile validation, image smoke test),
   - builds the multi-arch image (amd64, arm64) with `APP_VERSION=X.Y.Z` baked in and pushes
     `ghcr.io/tkint/study-companion:X.Y.Z`, `:X.Y` and `:latest`,
   - creates a GitHub Release with generated notes and attaches
     `study-companion-deploy.tar.gz` (compose file, `.env.example` with `IMAGE_TAG=latest`,
     shared `deploy/caddy/` project, `deploy/study-companion.caddy`, backup script),
     plus `docker-compose.yml`, `env.example` and `server-setup.md`.

The app reads its version from the `APP_VERSION` environment variable (set in the image from
the tag) and shows it in `/healthz`, the settings page and the MCP server info. Local runs
and images built without the build arg report `dev`.

## First release only: make the image public

GHCR packages are private when first created. Either make it public
(GitHub > your profile > Packages > study-companion > Package settings > Change visibility)
so the VPS can pull without credentials, or keep it private and run
`docker login ghcr.io -u tkint` on the VPS with a personal access token that has `read:packages`.

## Deploy to the VPS from GitHub (manual)

Releasing only publishes the image. To roll it out, open GitHub > Actions > **Deploy** >
**Run workflow** and pick the tag (`latest` or e.g. `0.5.0`). The workflow
(`.github/workflows/deploy.yml`) writes the app's `.env` from the settings below, uploads it
with the deploy files over SSH and runs `~/caddy/deploy.py` (see
[server-setup.md](server-setup.md#5-install-the-app)). No cron and no extra service on the
server; you never edit files on it.

1. On your computer create a dedicated key (`ssh-keygen -t ed25519 -f deploy_key -N ""`) and add
   `deploy_key.pub` to `~/.ssh/authorized_keys` of the deploy user on the server (a user in
   the `docker` group, not root). The server needs Python 3 and Docker Compose.
2. In GitHub > Settings > Environments, create `production` (add required reviewers if you
   want an approval step) and add:

   | Name | Kind | Value |
   | --- | --- | --- |
   | `DEPLOY_SSH_KEY` | secret | the private key `deploy_key` |
   | `DEPLOY_HOST` | variable | domain or IP of the server |
   | `DEPLOY_USER` | variable | the deploy user |
   | `DEPLOY_HOST_KEY` | variable | output of `ssh-keyscan -t ed25519 <host>` |
   | `DEPLOY_PORT` | variable | optional, 22 by default |
   | `DOMAIN` | variable | the app's hostname, e.g. `study-companion.ch` |
   | `SECRET_KEY` | secret | `openssl rand -hex 32`; when moving an existing install, its current value |
   | `APP_PASSWORD` | secret | web UI password for the very first start (12+ characters) |

   Optional, written to `.env` only when set (see `.env.example`): variables
   `MOODLE_URL`, `SYNC_INTERVAL_HOURS`, `MOODLE_MAX_FILE_MB`, `MOODLE_RATE_LIMIT`,
   `SESSION_MAX_AGE`, `COOKIE_SECURE`, `TIMEZONE`, `OAUTH_REDIRECT_HOSTS`,
   `OAUTH_ACCESS_TTL`, `OAUTH_REFRESH_TTL`, and secret `MOODLE_TOKEN`.

The `DEPLOY_*` values can be repository-level settings too. The workflow stops before
connecting if a required one is missing, without printing any value. `.env` is rewritten on
every run, so a setting changed in GitHub takes effect at the next deployment. The version
input becomes `IMAGE_TAG`. If the VPS firewall restricts SSH, allow GitHub-hosted runners or
use a self-hosted runner on the VPS.
