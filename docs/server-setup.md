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

Everything is deployed from GitHub; you don't need to log in to the server for it.

1. Set up the **Deploy** workflow once: SSH access and the app settings (`DOMAIN`,
   `SECRET_KEY`, `APP_PASSWORD`, ...) in the repository's `production` environment
   ([docs/releasing.md](releasing.md#deploy-to-the-vps-from-github-manual)).
2. Run **Actions > Deploy > Run workflow** with `latest`.

The workflow writes `~/study-companion/.env` from those settings (it replaces the file on every
run, so change settings in GitHub, not on the server), uploads the app's Compose file and
site, and uploads the shared Caddy to `~/caddy`. On the server, `~/caddy/deploy.py` then:

- creates the external `edge` network and starts Caddy if needed,
- pulls and starts the app (Compose project `study`; it publishes no ports),
- adds the site to Caddy through its admin API, or replaces it if already there.

Caddy keeps the configuration it receives through the API in its `caddy-config` volume and
resumes it after a restart; `bootstrap.json` is only used before the first site is added.
Other sites on the same Caddy are left alone, and deployments wait for each other.

To change the hostname, update `DOMAIN` in GitHub and run the workflow again. The site
proxies to the alias `study-companion-app:8000` on the `edge` network. If HTTPS doesn't come
up, check `cd ~/caddy && docker compose logs caddy`.

**Coming from a Caddy that ran inside this app's Compose project:** remove that container
once before the first deploy (`docker rm -f <old caddy container>`), and copy the
`SECRET_KEY` from the old `.env` into the GitHub secret: it encrypts the stored Moodle token.
The new Caddy requests its certificates again. Don't run `docker compose down -v`: it deletes
the app's data volume.

Open `https://study-companion.ch` on your phone and sign in. Then open **Settings**, enter
your Moodle address and paste your token ([docs/moodle-token.md](moodle-token.md) explains how
to get it with university SSO). The first sync starts right away; refresh the home page to
follow it. Use your browser's "Add to Home Screen" for quick access.

After the first start you can delete the `APP_PASSWORD` secret; change the password on the
Settings page instead.

## 6. Nightly backups

Follow [docs/backups.md](backups.md) to back up the data volume with restic every night.

## Update

Run the **Deploy** workflow with `latest` or a version such as `0.5.0`. Check the running version
with `docker compose exec app python -c "import app; print(app.__version__)"` in
`~/study-companion`.

## Troubleshooting

- **Certificate errors / Caddy keeps retrying:** the DNS record does not point to this server yet,
  or ports 80/443 are blocked (check both ufw and the Infomaniak firewall).
  Check `cd ~/caddy && docker compose logs caddy`.
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
