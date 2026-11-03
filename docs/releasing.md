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

## Automatic deploy to the VPS

After the image is pushed, the `deploy` job in `release.yml` can SSH into the server and run
`docker compose pull && docker compose up -d`. It is skipped unless `DEPLOY_HOST` is set, so
nothing changes until you configure it. No cron and no extra service on the server.

1. On the VPS, create a dedicated key pair on your computer
   (`ssh-keygen -t ed25519 -f deploy_key -N ""`), add `deploy_key.pub` to
   `~/.ssh/authorized_keys` of the user that owns `~/study` (a user in the `docker` group; do
   not use root).
2. In GitHub > Settings > Secrets and variables > Actions, add:
   - secret `DEPLOY_SSH_KEY`: contents of the private key `deploy_key`,
   - variables `DEPLOY_HOST` (domain or IP), `DEPLOY_USER`, `DEPLOY_HOST_KEY` (output of
     `ssh-keyscan -t ed25519 <host>`),
   - optional variables `DEPLOY_PORT` (default 22) and `DEPLOY_DIR` (default `~/study`).
3. The job uses an environment named `production`. Add required reviewers to it
   (Settings > Environments) if you want to approve each deploy.

`.env` must have `IMAGE_TAG=latest`. Compose file changes in a release (Caddyfile, compose)
still need the deploy bundle, see [server-setup.md](server-setup.md#update). If the VPS
firewall restricts SSH, allow GitHub-hosted runners or use a self-hosted runner on the VPS.
