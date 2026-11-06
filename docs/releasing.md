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
     shared `deploy/edge/` project, `deploy/study-companion.caddy`, backup script),
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
**Run workflow** and pick the tag (`latest` or e.g. `0.5.0`). The workflow SSHes into the
server, uploads the current deployment files and runs the shared-edge deployer
(`.github/workflows/deploy.yml`).
No cron and no extra service on the server. A version other than `latest` only applies to
that run; to stay on it permanently, set `IMAGE_TAG` in the server's `.env`.

1. On your computer create a dedicated key (`ssh-keygen -t ed25519 -f deploy_key -N ""`) and add
   `deploy_key.pub` to `~/.ssh/authorized_keys` of the user that owns `~/study-companion` (a user in the
   `docker` group, not root).
2. In GitHub > Settings > Secrets and variables > Actions, add:
   - secret `DEPLOY_SSH_KEY`: contents of the private key `deploy_key`,
   - variables `DEPLOY_HOST` (domain or IP), `DEPLOY_USER`, `DEPLOY_HOST_KEY` (output of
     `ssh-keyscan -t ed25519 <host>`),
   - optional variable `DEPLOY_PORT` (default 22).
3. The job uses an environment named `production`; add required reviewers to it
   (Settings > Environments) if you want an approval step.

The `DEPLOY_*` settings other than `DEPLOY_SSH_KEY` can also be stored as Actions secrets;
variables take precedence if both are set. Use repository-level settings or the
`production` environment, not a different environment. `DEPLOY_SSH_KEY` must be a secret.

If the run shows empty `HOST`, `SSH_USER`, or `HOST_KEY`, the corresponding settings are
missing or unavailable to the job. Add `DEPLOY_HOST`, `DEPLOY_USER`, and `DEPLOY_HOST_KEY`
under **Settings > Secrets and variables > Actions > Variables > New repository variable**
(or as secrets). Then rerun the workflow. It checks required settings before attempting SSH
and reports missing names without printing their values.

The server needs Python 3 and Docker Compose 2.24.4 or newer. Prepare `~/study-companion/.env`
before the first run. Each deployment installs the app Compose file, updates only this
app's site, and starts the shared Caddy if needed, even if the app or Caddy is absent.
It updates only this app's identified route through Caddy's local admin REST API. Caddy
persists that config and resumes it after restarts. The deployer preserves existing sites
and automatically migrates a standard app-owned Docker Caddy, including its certificates.
The shared edge lock serializes independent deployments.

The selected workflow ref supplies the deployment files; the version input selects the
app image. Manual deployment and migration details:
[server-setup.md](server-setup.md#update). If the VPS firewall restricts SSH, allow GitHub-hosted
runners or use a self-hosted runner on the VPS.
