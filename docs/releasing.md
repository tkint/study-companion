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
