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
> through Caddy on the internal Docker network. Keep the Infomaniak firewall from step 1 as a
> second layer.

## 4. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out and back in afterwards
docker compose version
```

## 5. Install the app

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

Start it:

```bash
docker compose up -d
docker compose logs -f caddy   # watch for "certificate obtained successfully", then Ctrl+C
```

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
updates it, with no cron or extra service. Setup: [docs/releasing.md](releasing.md#deploy-to-the-vps-from-github-manual).

**Manual:**

`docker compose pull` fetches the image named by `IMAGE_TAG` in `.env`. With
`IMAGE_TAG=latest` it follows new releases; with a version number (e.g. `0.1.0`) it stays on
that version.

```bash
cd ~/study
grep IMAGE_TAG .env                                       # should print IMAGE_TAG=latest
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=latest/' .env           # if it shows a version number
docker compose pull && docker compose up -d
docker compose exec app python -c "import app; print(app.__version__)"   # running version
```

Releases can also add deploy files (for example `deploy/backup.sh` in 0.2.0). Refresh them
without touching `.env` or your data:

```bash
cd ~/study
curl -fsSL https://github.com/tkint/study-companion/releases/latest/download/study-companion-deploy.tar.gz \
  | tar xz --strip-components=1 --exclude=.env.example
docker compose up -d
```

To pin a version instead, set `IMAGE_TAG=0.2.0` (for example) in `.env` and run the same
`pull` and `up -d`.

> The v0.1.0 release bundle shipped `.env.example` with `IMAGE_TAG=0.1.0`, so an `.env`
> copied from it stays on 0.1.0 until you change that line as shown above.

## Troubleshooting

- **`docker compose pull` doesn't update the app:** `IMAGE_TAG` in `.env` is pinned to an
  old version; set it to `latest` (see Update above).
- **Certificate errors / Caddy keeps retrying:** the DNS record does not point to this server yet,
  or ports 80/443 are blocked (check both ufw and the Infomaniak firewall).
- **App container restarting:** `docker compose logs app`. A missing or too short
  `SECRET_KEY`, or no `APP_PASSWORD` on the very first start, stops the app with a clear message.
- **Sync says the token is invalid or expired:** get a new one ([docs/moodle-token.md](moodle-token.md))
  and paste it on the Settings page.
- **Forgot the web UI password:** `docker compose exec app python -m app.cli reset-password`
  sets a new one and signs every device out.
- **Too many failed attempts:** the login locks for 15 minutes after 5 wrong passwords
  (restarting the app clears it).

Add the Claude connector next: [docs/connector.md](connector.md).
