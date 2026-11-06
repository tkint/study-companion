#!/usr/bin/env python3
"""Start the shared Caddy and one app, then add or replace the app's site through Caddy's admin API.

Usage: python3 ~/caddy/deploy.py APP_DIR COMPOSE_FILE SITE_FILE

APP_DIR holds the app's .env (with DOMAIN). The site's route gets the site file's name as its
@id, so each deployment replaces only its own site. Caddy autosaves every API change.
"""

import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time

CADDY_DIR = Path(__file__).resolve().parent
SERVER = "/config/apps/http/servers/srv0"


def run(*args, input=None, check=True):
    result = subprocess.run(args, input=input, text=True, capture_output=True)
    if check and result.returncode:
        sys.exit(f"{' '.join(args[:4])} failed:\n{result.stderr or result.stdout}")
    return result


def caddy(*args, input=None, check=True):
    return run("docker", "compose", "--project-directory", str(CADDY_DIR), *args,
               input=input, check=check)


def api(method, path, body=None, check=True):
    args = ["exec", "-T", "caddy", "curl", "-sS", "-w", "\n%{http_code}", "-X", method,
            f"http://localhost:2019{path}"]
    if body is not None:
        args += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
    result = caddy(*args, input=None if body is None else json.dumps(body), check=check)
    text, _, status = result.stdout.rpartition("\n")
    ok = result.returncode == 0 and status.startswith("2")
    if check and not ok:
        sys.exit(f"Caddy API {method} {path} failed ({status}): {text or result.stderr}")
    return json.loads(text) if ok and text.strip() else None


def main(app_dir, compose_file, site_file):
    app = Path(app_dir).expanduser().resolve()
    settings = dict(
        line.split("=", 1) for line in (app / ".env").read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    domain = settings.get("DOMAIN", "").strip()
    if not domain:
        sys.exit(f"DOMAIN is missing from {app / '.env'}.")

    if run("docker", "network", "inspect", "edge", check=False).returncode:
        run("docker", "network", "create", "edge")
    caddy("up", "-d")
    for _ in range(30):
        if api("GET", "/config/", check=False) is not None:
            break
        time.sleep(1)
    else:
        sys.exit("Caddy's admin API did not answer.")

    run("docker", "compose", "--project-directory", str(app), "--env-file", str(app / ".env"),
        "-f", str(app / compose_file), "pull")
    run("docker", "compose", "--project-directory", str(app), "--env-file", str(app / ".env"),
        "-f", str(app / compose_file), "up", "-d", "--wait")

    site = (app / site_file).read_text().replace("{$DOMAIN}", domain)
    adapted = json.loads(caddy("exec", "-T", "caddy", "caddy", "adapt", "--adapter", "caddyfile",
                               "--config", "/dev/stdin", input=site).stdout)
    server = next(iter(adapted["apps"]["http"]["servers"].values()))
    if len(server["routes"]) != 1:
        sys.exit(f"{site_file} must define exactly one site.")
    route = {**server["routes"][0], "@id": Path(site_file).stem}

    config = api("GET", "/config/") or {}
    new_logs = adapted.get("logging", {}).get("logs", {})
    if new_logs:
        logs = config.get("logging", {}).get("logs", {})
        excluded = set(logs.get("default", {}).get("exclude", []))
        excluded |= set(new_logs.get("default", {}).get("exclude", []))
        logs.update({name: log for name, log in new_logs.items() if name != "default"})
        logs["default"] = {**logs.get("default", {}), "exclude": sorted(excluded)}
        api("POST", "/config/logging", {**config.get("logging", {}), "logs": logs})
    if "logs" in server:
        current = config["apps"]["http"]["servers"]["srv0"].get("logs", {})
        names = {**current.get("logger_names", {}), **server["logs"].get("logger_names", {})}
        api("POST", f"{SERVER}/logs",
            {**current, "logger_names": names, "skip_unmapped_hosts": True})

    if api("GET", f"/id/{route['@id']}", check=False) is None:
        api("POST", f"{SERVER}/routes", route)
    else:
        api("PATCH", f"/id/{route['@id']}", route)
    print(f"Deployed https://{domain}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    with open(CADDY_DIR / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        main(*sys.argv[1:])
