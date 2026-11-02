#!/usr/bin/env bash
# Nightly encrypted backup of the app's data volume with restic (run on the VPS host).
#
#   1. Takes a consistent SQLite snapshot inside the running app container.
#   2. Backs up the data volume (snapshot + course files) with the official restic image,
#      so restic does not need to be installed on the host.
#   3. Applies the retention policy and prunes old data.
#
# Configuration: deploy/backup.env next to this script (chmod 600), see docs/backups.md:
#   RESTIC_REPOSITORY=...   e.g. s3:https://s3.swiss-backup04.infomaniak.com/study-backup
#   RESTIC_PASSWORD=...     keep a copy somewhere safe: without it the backup is useless
#   AWS_ACCESS_KEY_ID=... / AWS_SECRET_ACCESS_KEY=...   for S3-compatible storage
#
# Usage: deploy/backup.sh [backup|init|snapshots|check|restore <snapshot> <target-dir>]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(dirname "$here")"
env_file="${BACKUP_ENV:-$here/backup.env}"
restic_image="${RESTIC_IMAGE:-restic/restic:0.17.3}"
keep="${RESTIC_KEEP:---keep-daily 7 --keep-weekly 4 --keep-monthly 6}"

if [[ ! -f "$env_file" ]]; then
  echo "Missing $env_file (see docs/backups.md)" >&2
  exit 2
fi

cd "$project_dir"
# The compose project's data volume, e.g. "study_app-data".
volume="$(docker compose config --format json \
  | python3 -c 'import json,sys; c=json.load(sys.stdin); print(c["volumes"]["app-data"]["name"])' 2>/dev/null \
  || echo "$(basename "$project_dir")_app-data")"

restic() {
  docker run --rm -i \
    --env-file "$env_file" \
    -e RESTIC_CACHE_DIR=/cache \
    -v restic-cache:/cache \
    -v "$volume":/data:ro \
    --hostname study-companion \
    "$restic_image" "$@"
}

cmd="${1:-backup}"
case "$cmd" in
  init)
    restic init
    ;;
  backup)
    echo "$(date -Is) snapshotting database"
    docker compose exec -T app python -m app.cli snapshot-db
    echo "$(date -Is) backing up volume $volume"
    # The live database files are skipped; backup/app.db is the consistent copy.
    restic backup /data --tag study-companion \
      --exclude /data/app.db --exclude /data/app.db-wal --exclude /data/app.db-shm \
      --exclude '*.part'
    # shellcheck disable=SC2086
    restic forget --tag study-companion --prune $keep
    echo "$(date -Is) backup done"
    ;;
  snapshots)
    restic snapshots
    ;;
  check)
    restic check
    ;;
  restore)
    snapshot="${2:?snapshot id (or latest)}"
    target="${3:?target directory on the host}"
    mkdir -p "$target"
    docker run --rm -i --env-file "$env_file" -v "$(cd "$target" && pwd)":/restore \
      "$restic_image" restore "$snapshot" --target /restore
    echo "Restored into $target/data (database copy: $target/data/backup/app.db)"
    ;;
  *)
    echo "Usage: $0 [backup|init|snapshots|check|restore <snapshot> <target-dir>]" >&2
    exit 2
    ;;
esac
