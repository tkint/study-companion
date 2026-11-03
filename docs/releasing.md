# Releasing

Releases are fully automated from a version tag.

1. Bump `__version__` in `backend/app/__init__.py` (semantic versioning) and merge to `main`.
2. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

3. `.github/workflows/release.yml` then:
   - runs the CI workflow (tests, compose/Caddyfile validation, image smoke test),
   - checks the tag matches `__version__`,
   - builds the multi-arch image (amd64, arm64) and pushes
     `ghcr.io/tkint/study-companion:X.Y.Z`, `:X.Y` and `:latest`,
   - creates a GitHub Release with generated notes and attaches
     `study-companion-deploy.tar.gz` (compose file, `.env.example` with `IMAGE_TAG=latest`,
     Caddyfile, backup script), plus `docker-compose.yml`, `env.example` and `server-setup.md`.

## First release only: make the image public

GHCR packages are private when first created. Either make it public
(GitHub > your profile > Packages > study-companion > Package settings > Change visibility)
so the VPS can pull without credentials, or keep it private and run
`docker login ghcr.io -u tkint` on the VPS with a personal access token that has `read:packages`.

## Deploy to the VPS from GitHub (manual)

Releasing only publishes the image. To roll it out, open GitHub > Actions > **Deploy** >
**Run workflow** and pick the tag (`latest` or e.g. `0.5.0`). The workflow SSHes into the
server and runs `docker compose pull && docker compose up -d` (`.github/workflows/deploy.yml`).
No cron and no extra service on the server. A version other than `latest` only applies to
that run; to stay on it permanently, set `IMAGE_TAG` in the server's `.env`.

1. On your computer create a dedicated key (`ssh-keygen -t ed25519 -f deploy_key -N ""`) and add
   `deploy_key.pub` to `~/.ssh/authorized_keys` of the user that owns `~/study` (a user in the
   `docker` group, not root).
2. In GitHub > Settings > Secrets and variables > Actions, add:
   - secret `DEPLOY_SSH_KEY`: contents of the private key `deploy_key`,
   - variables `DEPLOY_HOST` (domain or IP), `DEPLOY_USER`, `DEPLOY_HOST_KEY` (output of
     `ssh-keyscan -t ed25519 <host>`),
   - optional variables `DEPLOY_PORT` (default 22) and `DEPLOY_DIR` (default `~/study`).
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

Changes to the Caddyfile or compose file still need the deploy bundle, see
[server-setup.md](server-setup.md#update). If the VPS firewall restricts SSH, allow GitHub-hosted
runners or use a self-hosted runner on the VPS.
