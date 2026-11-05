#!/usr/bin/env bash
set -euo pipefail

require() {
  if [ -z "$1" ]; then
    echo "::error::Missing $2. Configure the production environment or repository Actions settings."
    exit 1
  fi
}

require "${SSH_KEY:-}" DEPLOY_SSH_KEY
require "${HOST:-}" DEPLOY_HOST
require "${SSH_USER:-}" DEPLOY_USER
require "${HOST_KEY:-}" DEPLOY_HOST_KEY
require "${DEPLOY_DIR:-}" DEPLOY_DIR
require "${VERSION:-}" version
if ! printf '%s' "$VERSION" | grep -Eq '^[A-Za-z0-9._-]+$'; then
  echo "::error::Invalid image version."
  exit 1
fi

compose_file=$1
site_file=$2
credentials=$(mktemp -d)
trap 'rm -f "$credentials/key" "$credentials/known_hosts"; rmdir "$credentials"' EXIT
printf '%s\n' "$SSH_KEY" > "$credentials/key"
printf '%s\n' "$HOST_KEY" > "$credentials/known_hosts"
chmod 600 "$credentials/key" "$credentials/known_hosts"

# Quote arguments for the remote shell, then unpack only regular files in a temporary directory.
edge_dir=${EDGE_DIR:-'~/edge'}
remote_command=$(python3 - "$DEPLOY_DIR" "$edge_dir" "$VERSION" "$compose_file" "$site_file" <<'PY'
import shlex
import sys

code = """
import pathlib
import subprocess
import sys
import tarfile
import tempfile

with tempfile.TemporaryDirectory(prefix="edge-upload-") as directory:
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
        for member in archive:
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe deployment archive entry")
            archive.extract(member, directory)
    result = subprocess.run([
        sys.executable, "deploy/edge/deploy.py",
        "--app-dir", sys.argv[1], "--edge-dir", sys.argv[2], "--version", sys.argv[3],
        "--compose-file", sys.argv[4], "--site-file", sys.argv[5],
    ], cwd=directory)
    status = result.returncode
sys.exit(status)
"""
print(shlex.join(["python3", "-c", code, *sys.argv[1:]]))
PY
)
tar -czf - "$compose_file" "$site_file" deploy/edge |
  ssh -i "$credentials/key" -p "${SSH_PORT:-22}" -o BatchMode=yes \
    -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$credentials/known_hosts" \
    "$SSH_USER@$HOST" "$remote_command"
