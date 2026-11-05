# Server setup: VPS, domain, HTTPS and install

This guide takes you from nothing to `https://study.<your-domain>` opening on your phone.
It targets an **Infomaniak VPS Lite** (Geneva) running Debian 12 or Ubuntu 24.04, but any
small Linux VPS works.

## 1. Order the VPS

1. Order [Infomaniak VPS Lite](https://www.infomaniak.com/en/hosting/vps-lite): 1 vCPU, 2 GB RAM,
   20 GB NVMe is enough (the server does no AI work). Pick the bigger plan only if your courses
   contain lots of video.
2. Choose **Debian 12** or **Ubuntu 24.04** and add your **SSH public key** during the order.
   (No key yet? `ssh-keygen -t ed25519` on your computer, then paste `~/.ssh/id_ed25519.pub`.)
3. Note the server's public IPv4 (and IPv6 if shown).
4. In the Infomaniak manager, open the VPS firewall and allow only **TCP 22, 80, 443** and
   **UDP 443** (HTTP/3). Everything else stays closed.

## 2. Point a domain at it

Create DNS records at your domain registrar (for Infomaniak domains: Manager > Domains > DNS zone):

| Type | Name    | Value              |
| ---- | ------- | ------------------ |
| A    | `study` | your VPS IPv4      |
| AAAA | `study` | your VPS IPv6 (optional) |

Check it resolves before continuing: `dig +short study-companion.ch` should print the IP.
Caddy needs this to obtain the HTTPS certificate.

## 3. Harden the server

Log in as the default user (`ssh debian@<ip>` or `ssh ubuntu@<ip>`; Infomaniak shows it) and
run the following. Replace `me` with the username you want.

```bash
# Updates and basics
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y ufw fail2ban unattended-upgrades curl ca-certificates

# Your own sudo user with your SSH key (skip if you keep the default user)
sudo adduser --disabled-password --gecos "" me
sudo usermod -aG sudo me
sudo mkdir -p /home/me/.ssh && sudo cp ~/.ssh/authorized_keys /home/me/.ssh/
sudo chown -R me:me /home/me/.ssh && sudo chmod 700 /home/me/.ssh && sudo chmod 600 /home/me/.ssh/authorized_keys
echo "me ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/90-me   # or set a password instead
```

Open a **second terminal** and check `ssh me@<ip>` works before going on.

```bash
# SSH: keys only, no root login
sudo tee /etc/ssh/sshd_config.d/99-hardening.conf >/dev/null <<'CONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
CONF
sudo systemctl restart ssh

# Firewall: only SSH, HTTP, HTTPS
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw --force enable

# fail2ban protects SSH with its default jail
sudo tee /etc/fail2ban/jail.d/sshd.local >/dev/null <<'CONF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
bantime = 1h
CONF
sudo systemctl enable --now fail2ban

# Automatic security updates
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
```

> **Docker and ufw:** ports published by Docker bypass ufw rules. That is fine here because only
> Caddy publishes ports (80 and 443); the app container publishes none and is reachable only
> through Caddy on the shared edge network. Keep the Infomaniak firewall from step 1 as a
> second layer.

## 4. Install Docker

Use Docker Compose 2.24.4 or newer.

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out and back in afterwards
docker compose version
sudo apt install -y python3
```

## 5. Install the app

For an existing installation, keep its `.env`, directory and Compose project name.
The deployment command below also handles upgrades and automatically migrates an
app-owned Caddy; see [migration details](#automatic-caddy-migration).

```bash
mkdir -p ~/study && cd ~/study
curl -fsSL https://github.com/tkint/study-companion/releases/latest/download/study-companion-deploy.tar.gz \
  | tar xz --strip-components=1
cp .env.example .env
chmod 600 .env
nano .env
```

Fill in `.env`:

- `DOMAIN`: your subdomain, e.g. `study-companion.ch`
- `APP_PASSWORD`: a long password for the web UI (12+ characters)
- `SECRET_KEY`: output of `openssl rand -hex 32`
- `MOODLE_URL`, `MOODLE_TOKEN`: leave them out; you connect Moodle on the Settings page

### Deploy the app and shared Caddy

```bash
cd ~/study
python3 deploy/edge/deploy.py --app-dir . \
  --compose-file docker-compose.yml --site-file deploy/study-companion.caddy
```

The app's Compose file runs only the app. Deployment creates the external `edge` network,
renders `DOMAIN` into its own site file, validates the combined Caddy configuration, pulls
the images and starts or updates both projects. Caddy lives independently in `~/edge` and
is started if absent or stopped, regardless of whether the app already exists.

Existing site files and a customized edge `Caddyfile` are preserved. Repeated deployments
update this app's site and reload a running Caddy. A host-level lock serializes changes
from independent deployments. All deployments sharing Caddy must use the same edge
directory, Compose project and external network.

Use `--edge-dir /path/to/edge` to change the shared directory. `EDGE_NETWORK` in the
app's `.env` defaults to `edge`; if customized, the edge's network must match.
Do not combine the edge and app Compose files into one project. `docker compose down`
in the app directory leaves Caddy running. The shared network is for trusted apps;
containers on it can reach each other's app ports.

The site retains the security headers and query-string secret redaction and proxies to
the unique alias `study-companion-app:8000`. Check `cd ~/edge && docker compose logs caddy`
if HTTPS does not become available.

Open `https://study-companion.ch` on your phone and sign in. Then open **Settings**, enter
your Moodle address and paste your token ([docs/moodle-token.md](moodle-token.md) explains how
to get it with university SSO). The first sync starts right away; refresh the home page to
follow it. Use your browser's "Add to Home Screen" for quick access.

After the first start you can remove `APP_PASSWORD` from `.env`; change the password on the
Settings page instead.

## 6. Nightly backups

Follow [docs/backups.md](backups.md) to back up the data volume with restic every night.

## Update

**From GitHub:** run the **Deploy** workflow in GitHub Actions; it SSHes into this server and
uploads the deployment files, updates the app and reconciles the shared Caddy.
Setup: [docs/releasing.md](releasing.md#deploy-to-the-vps-from-github-manual).

**Manual:**

Refresh the bundle in a staging directory so the running installation remains available
for automatic migration. Keep the existing app directory/project name and `.env`:

```bash
mkdir -p ~/study-deploy && cd ~/study-deploy
curl -fsSL https://github.com/tkint/study-companion/releases/latest/download/study-companion-deploy.tar.gz \
  | tar xz --strip-components=1
python3 deploy/edge/deploy.py --app-dir ~/study \
  --compose-file docker-compose.yml --site-file deploy/study-companion.caddy --version latest
cd ~/study
docker compose exec app python -c "import app; print(app.__version__)"   # running version
```

Omit `--version` to use `IMAGE_TAG` from `.env`, or pass a version to pin that deployment.
The workflow uses deployment files from its checked-out ref and the selected image tag.
It never overwrites `.env` or other apps' site files. To change the hostname or the site's
configuration, update `.env` or the source site template and redeploy; the same path
handles a running, stopped or absent Caddy.

For direct edge inspection, include the migration override when present:

```bash
cd ~/edge
docker compose -f compose.yaml -f migration.compose.json ps
```

Omit `-f migration.compose.json` if no migration took place; also include
`-f compose.override.yaml` if you customized the edge. Deployment supplies these
automatically. Caddy runs the generated `generated/caddy.json`, not the source Caddyfile.
Do not edit generated JSON by hand.

## Automatic Caddy migration

Back up [app data](backups.md) and `.env` first. The deployer discovers a Docker Caddy
owning host ports 80/443, including a stopped container. It adapts the mounted Caddyfile
with the old container's environment, retains existing sites and network connectivity,
and reuses its named `/data` and `/config` volumes. It rewrites Docker upstream aliases
to unique container names so a new service cannot shadow an existing upstream.

The generated shared configuration replaces only the redeployed hostname's legacy
route. Other routes remain until their owners redeploy. Legacy networks are detached
once no legacy proxy routes remain. Keep `legacy.json`, `migration.compose.json` and the
original certificate volumes: they are active deployment state, not disposable backups.

The swap briefly interrupts HTTPS. Configuration is validated before stopping the old
Caddy. If starting the new edge fails, deployment restores the saved edge files and
restarts the original Caddy. An application update may already have completed; a failed
deployment reports this rather than claiming the entire application was rolled back.

Ambiguous port owners, non-Caddy containers, custom legacy mounts/config paths, and
conflicting Caddy settings fail explicitly without stopping the existing proxy. A
host-installed Caddy needs explicit manual migration. Never use `docker compose down -v`
to clean up a migrated stack.

## Troubleshooting

- **`docker compose pull` doesn't update the app:** `IMAGE_TAG` in `.env` is pinned to an
  old version; set it to `latest` (see Update above).
- **Certificate errors / Caddy keeps retrying:** the DNS record does not point to this server yet,
  or ports 80/443 are blocked (check both ufw and the Infomaniak firewall).
  Check `cd ~/edge && docker compose logs caddy`.
- **Network `edge` not found:** create it once with `docker network create edge`.
- **502 from Caddy:** check the app is running and attached to `edge`; the site's upstream
  must be `study-companion-app:8000`, not the ambiguous name `app:8000`.
- **App container restarting:** `docker compose logs app`. A missing or too short
  `SECRET_KEY`, or no `APP_PASSWORD` on the very first start, stops the app with a clear message.
- **Sync says the token is invalid or expired:** get a new one ([docs/moodle-token.md](moodle-token.md))
  and paste it on the Settings page.
- **Forgot the web UI password:** `docker compose exec app python -m app.cli reset-password`
  sets a new one and signs every device out.
- **Too many failed attempts:** the login locks for 15 minutes after 5 wrong passwords
  (restarting the app clears it).

Add the Claude connector next: [docs/connector.md](connector.md).
