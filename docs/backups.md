# Backups (restic, nightly)

VPS Lite has no snapshots, so the app's data volume (SQLite database and downloaded course
files) is backed up every night with [restic](https://restic.net): encrypted, deduplicated,
with a retention policy. `deploy/backup.sh` runs restic from its official Docker image, so
nothing extra is installed on the server.

What is backed up: a consistent copy of the database (`backup/app.db`, taken with SQLite's
backup API while the app runs) and everything under `/data/courses`. The Moodle token in the
database is encrypted with `SECRET_KEY`, so **keep a copy of `SECRET_KEY`**
(the GitHub secret) somewhere safe as well; restoring without it means pasting the token again.

## 1. Choose where backups go

Keep backups off the VPS. Two simple Swiss options:

- **Infomaniak Swiss Backup** (S3-compatible). Create an S3 device in the Infomaniak manager;
  it gives you an endpoint, access key and secret key. Repository:
  `s3:https://<endpoint>/<bucket-name>`.
- **Any SFTP server** you control. Repository: `sftp:user@host:/path/study-backup`
  (needs an SSH key mounted into the restic container; S3 is simpler with this script).

## 2. Configure

On the server, in the app folder (e.g. `~/study-companion`):

```bash
cat > deploy/backup.env <<'EOF'
RESTIC_REPOSITORY=s3:https://s3.swiss-backup04.infomaniak.com/study-backup
RESTIC_PASSWORD=<output of: openssl rand -base64 32>
AWS_ACCESS_KEY_ID=<access key>
AWS_SECRET_ACCESS_KEY=<secret key>
EOF
chmod 600 deploy/backup.env
```

Store `RESTIC_PASSWORD` in your password manager: without it the backups can't be read.

Initialise the repository once and run a first backup:

```bash
deploy/backup.sh init
deploy/backup.sh backup
deploy/backup.sh snapshots
```

## 3. Schedule it nightly

```bash
crontab -e
```

Add (03:30 every night, log to a file):

```
30 3 * * * cd $HOME/study-companion && deploy/backup.sh backup >> $HOME/study-companion/backup.log 2>&1
```

Retention: 7 daily, 4 weekly and 6 monthly snapshots (`RESTIC_KEEP` overrides it). Run
`deploy/backup.sh check` from time to time to verify the repository.

## Restore

```bash
cd ~/study-companion
deploy/backup.sh snapshots                 # pick a snapshot id, or use "latest"
deploy/backup.sh restore latest /tmp/restore
docker compose down
# Copy the restored files into the volume, putting the database copy in place:
docker run --rm -v study_app-data:/data -v /tmp/restore/data:/restore alpine \
  sh -c 'cp -a /restore/. /data/ && cp /restore/backup/app.db /data/app.db && rm -f /data/app.db-wal /data/app.db-shm && chown -R 1000:1000 /data'
docker compose up -d
```

(`study_app-data` is the volume name; check with
`docker volume ls`.)
