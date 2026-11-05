#!/usr/bin/env python3
"""Deploy one application and reconcile the host's shared Caddy."""

import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


class DeployError(Exception):
    pass


def run(args, *, cwd=None, env=None, input=None):
    result = subprocess.run(
        args, cwd=cwd, env=env, input=input, text=True, capture_output=True
    )
    if result.returncode:
        raise DeployError(f"{' '.join(args[:2])} failed:\n{result.stderr.strip()}")
    return result.stdout


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content if isinstance(content, bytes) else content.encode())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def merge(left, right, path="config"):
    """Combine compatible settings; never silently replace legacy settings."""
    if left == right:
        return copy.deepcopy(left)
    if isinstance(left, dict) and isinstance(right, dict):
        result = copy.deepcopy(left)
        for key, value in right.items():
            result[key] = (
                merge(result[key], value, f"{path}.{key}") if key in result else copy.deepcopy(value)
            )
        return result
    if isinstance(left, list) and isinstance(right, list):
        if left and right and path.endswith(("tls_connection_policies", "automation.policies")):
            raise DeployError(f"Incompatible existing Caddy policies at {path}; migration was not applied.")
        return copy.deepcopy(left + [value for value in right if value not in left])
    raise DeployError(f"Incompatible existing Caddy setting at {path}; migration was not applied.")


def without_hosts(value, hosts):
    if isinstance(value, list):
        return [item for entry in value if (item := without_hosts(entry, hosts)) is not None]
    if not isinstance(value, dict):
        return value
    result = copy.deepcopy(value)
    if "match" in result:
        matchers = []
        for matcher in result["match"]:
            if "host" in matcher:
                matcher["host"] = [host for host in matcher["host"] if host not in hosts]
                if not matcher["host"]:
                    continue
            matchers.append(matcher)
        if not matchers:
            return None
        result["match"] = matchers
    return {key: without_hosts(item, hosts) for key, item in result.items()}


def site_hosts(value):
    if isinstance(value, list):
        return set().union(*(site_hosts(item) for item in value))
    if isinstance(value, dict):
        hosts = set()
        for matcher in value.get("match", []):
            hosts.update(matcher.get("host", []))
        return hosts | set().union(*(site_hosts(item) for item in value.values()))
    return set()


def combine(managed, legacy):
    legacy = without_hosts(legacy, site_hosts(managed))
    current = copy.deepcopy(managed)
    previous = copy.deepcopy(legacy)
    servers = current.get("apps", {}).get("http", {}).pop("servers", {})
    old_servers = previous.get("apps", {}).get("http", {}).pop("servers", {})
    for server in old_servers.values():
        listeners = sorted(server.get("listen", []))
        match = next(
            (key for key, value in servers.items() if sorted(value.get("listen", [])) == listeners),
            None,
        )
        if match is None:
            servers[f"legacy{len(servers)}"] = server
        else:
            servers[match] = merge(servers[match], server, "http.server")
    result = merge(current, previous)
    result.setdefault("apps", {}).setdefault("http", {})["servers"] = servers
    return result, legacy


def has_proxy(value):
    if isinstance(value, dict):
        return value.get("handler") == "reverse_proxy" or any(has_proxy(item) for item in value.values())
    return isinstance(value, list) and any(has_proxy(item) for item in value)


def legacy_candidate(containers, project):
    candidates = []
    for container in containers:
        labels = container["Config"].get("Labels") or {}
        if labels.get("com.docker.compose.project") == project:
            continue
        bindings = container["HostConfig"].get("PortBindings") or {}
        owns_ports = any(
            binding.get("HostPort") in {"80", "443"}
            for entries in bindings.values()
            for binding in entries or []
        )
        if owns_ports:
            candidates.append(container)
    running = [item for item in candidates if item["State"]["Running"]]
    candidates = running or candidates
    if len(candidates) > 1:
        raise DeployError("Multiple containers own HTTP/HTTPS ports; refusing an ambiguous migration.")
    if not candidates:
        return None
    candidate = candidates[0]
    command = candidate["Config"].get("Cmd") or []
    if "caddy" not in command:
        raise DeployError("HTTP/HTTPS ports belong to a non-Caddy container; nothing was stopped.")
    return candidate


def export_legacy(container, containers):
    mounts = {mount["Destination"]: mount for mount in container["Mounts"]}
    if any(mounts.get(path, {}).get("Type") != "volume" for path in ("/data", "/config")):
        raise DeployError("Automatic migration requires named Caddy /data and /config volumes.")
    if set(mounts) - {"/data", "/config", "/etc/caddy/Caddyfile"}:
        raise DeployError("Existing Caddy has custom mounts; migrate those explicitly before deploying.")
    command = container["Config"].get("Cmd") or []
    if "--config" in command and command[command.index("--config") + 1] != "/etc/caddy/Caddyfile":
        raise DeployError("Automatic migration requires the standard /etc/caddy/Caddyfile.")
    environment = container["Config"].get("Env") or []
    if any("\n" in item or "\r" in item for item in environment):
        raise DeployError("Existing Caddy has multiline environment values; migrate it explicitly.")
    config = json.loads(run(
        ["docker", "run", "--rm", "--volumes-from", f"{container['Id']}:ro",
         "--env-file", "/dev/stdin", container["Config"]["Image"],
         "caddy", "adapt", "--config", "/etc/caddy/Caddyfile"],
        input="\n".join(environment) + "\n",
    ))
    networks = list(container["NetworkSettings"]["Networks"])
    aliases = {}
    for peer in containers:
        for name, network in peer["NetworkSettings"]["Networks"].items():
            if name in networks:
                for alias in network.get("Aliases") or []:
                    aliases.setdefault(alias, set()).add(peer["Name"].lstrip("/"))

    def unique_upstreams(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "dial" and isinstance(item, str):
                    host, separator, port = item.rpartition(":")
                    matches = aliases.get(host, set())
                    if separator and len(matches) == 1:
                        value[key] = f"{next(iter(matches))}:{port}"
                    elif separator and len(matches) > 1:
                        raise DeployError("An existing upstream has ambiguous Docker DNS aliases.")
                else:
                    unique_upstreams(item)
        elif isinstance(value, list):
            for item in value:
                unique_upstreams(item)

    unique_upstreams(config)
    override = {
        "volumes": {
            "caddy-data": {"external": True, "name": mounts["/data"]["Name"]},
            "caddy-config": {"external": True, "name": mounts["/config"]["Name"]},
        },
        "networks": {
            f"legacy{index}": {"external": True, "name": name}
            for index, name in enumerate(networks)
        },
    }
    override["services"] = {
        "caddy": {"networks": ["edge", *override["networks"]]}
    }
    return config, override


def deploy(args):
    app = args.app_dir.expanduser().resolve()
    edge = args.edge_dir.expanduser().resolve()
    source = Path(__file__).resolve().parent
    compose_source = args.compose_file.resolve()
    site_source = args.site_file.resolve()
    if app == edge:
        raise DeployError("The app and shared edge must have separate directories.")
    if not (app / ".env").is_file():
        raise DeployError(f"Prepare {app / '.env'} with the app's settings before deploying.")
    edge.mkdir(parents=True, exist_ok=True)
    with (edge / ".deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        reconcile(args, app, edge, source, compose_source, site_source)


def reconcile(args, app, edge, source, compose_source, site_source):
    app_env = dict(os.environ)
    if args.version:
        app_env["IMAGE_TAG"] = args.version
    edge_env = {
        key: value for key, value in os.environ.items()
        if key not in {"IMAGE_TAG", "COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_ENV_FILES"}
    }

    def app_compose(*command, installed=False):
        path = app / compose_source.name if installed else compose_source
        return run(
            ["docker", "compose", "--project-directory", str(app), "--env-file", str(app / ".env"),
             "-f", str(path), *command], cwd=app, env=app_env,
        )

    app_config = json.loads(app_compose("config", "--format", "json"))
    if "caddy" in app_config["services"] or any(
        service.get("ports") for service in app_config["services"].values()
    ):
        raise DeployError("The app Compose file must not contain Caddy or publish host ports.")
    variables = dict(
        line.split("=", 1) for line in app_compose("config", "--environment").splitlines()
        if "=" in line
    )
    domain = variables.get("DOMAIN", "")
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if len(domain) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", domain):
        raise DeployError("Set DOMAIN in the app's .env to a hostname, without a scheme, port or path.")
    site = site_source.read_text()
    if site.count("{$DOMAIN}") != 1:
        raise DeployError("The app site template must contain exactly one {$DOMAIN} placeholder.")
    site = site.replace("{$DOMAIN}", domain)

    targets = [
        edge / "compose.yaml", edge / "Caddyfile", edge / "generated/caddy.json",
        edge / "legacy.json", edge / "migration.compose.json", edge / "sites" / site_source.name,
        app / compose_source.name,
    ]
    backups = {path: path.read_bytes() if path.exists() else None for path in targets}
    old = None
    old_running = False
    edge_changed = False
    shared_existed = False

    def edge_compose(*command):
        files = ["-f", str(edge / "compose.yaml")]
        for name in ("compose.override.yaml", "migration.compose.json"):
            if (edge / name).exists():
                files += ["-f", str(edge / name)]
        return run(
            ["docker", "compose", "--project-directory", str(edge), *files, *command],
            cwd=edge, env=edge_env,
        )

    try:
        write(edge / "compose.yaml", (source / "compose.yaml").read_bytes())
        if not (edge / "Caddyfile").exists():
            write(edge / "Caddyfile", (source / "Caddyfile").read_bytes())
        edge_config = json.loads(edge_compose("config", "--format", "json"))
        project = edge_config["name"]
        if app_config["name"] == project:
            raise DeployError("The app and shared edge must have different Compose project names.")
        network = edge_config["networks"]["edge"]["name"]
        if app_config.get("networks", {}).get("edge", {}).get("name") != network:
            raise DeployError("The app and shared edge must use the same external edge network.")
        existing_networks = run(["docker", "network", "ls", "--format", "{{.Name}}"]).splitlines()
        if network not in existing_networks:
            run(["docker", "network", "create", network])
        ids = run(["docker", "ps", "-aq"]).split()
        containers = json.loads(run(["docker", "inspect", *ids])) if ids else []
        shared = [
            item for item in containers if
            (item["Config"].get("Labels") or {}).get("com.docker.compose.project") == project
            and (item["Config"].get("Labels") or {}).get("com.docker.compose.service") == "caddy"
        ]
        if len(shared) > 1:
            raise DeployError("Multiple shared Caddy containers exist; inspect the edge project before deploying.")
        shared_existed = bool(shared)
        if shared_existed:
            working_dir = shared[0]["Config"]["Labels"].get("com.docker.compose.project.working_dir")
            if working_dir and Path(working_dir).resolve() != edge:
                raise DeployError("The shared Caddy belongs to a different directory; set EDGE_DIR to that directory.")
        image = edge_config["services"]["caddy"]["image"]
        if not args.no_pull:
            app_compose("pull")
            edge_compose("pull")
        legacy_path = edge / "legacy.json"
        legacy = json.loads(legacy_path.read_text()) if legacy_path.exists() else {}
        migration_path = edge / "migration.compose.json"
        migration = json.loads(migration_path.read_text()) if migration_path.exists() else None
        if not shared_existed:
            old = legacy_candidate(containers, project)
            if old:
                if legacy or migration:
                    raise DeployError("Legacy migration state already exists; refusing to overwrite it.")
                legacy, migration = export_legacy(old, containers)
                old_running = old["State"]["Running"]

        with tempfile.TemporaryDirectory(prefix=".deploy-", dir=edge) as temporary:
            staging = Path(temporary)
            sites = staging / "sites"
            shutil.copytree(edge / "sites", sites) if (edge / "sites").exists() else sites.mkdir()
            write(sites / site_source.name, site)
            managed = json.loads(run(
                ["docker", "run", "--rm", "-v", f"{edge / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
                 "-v", f"{sites}:/etc/caddy/sites:ro", image,
                 "caddy", "adapt", "--config", "/etc/caddy/Caddyfile"],
            ))
            combined, remaining = combine(managed, legacy)
            if combined.get("admin", {}).get("disabled"):
                raise DeployError("The shared Caddy requires an enabled admin endpoint for controlled reloads.")
            candidate = staging / "caddy.json"
            write(candidate, json.dumps(combined))
            validation = ["docker", "run", "--rm"]
            if old:
                validation += ["--volumes-from", f"{old['Id']}:ro"]
            validation += [
                "-v", f"{candidate}:/tmp/caddy.json:ro", image,
                "caddy", "validate", "--config", "/tmp/caddy.json",
            ]
            run(validation)
            if migration and not has_proxy(remaining):
                migration.pop("networks", None)
                migration["services"]["caddy"]["networks"] = ["edge"]

            write(app / compose_source.name, compose_source.read_bytes())
            app_compose("up", "-d", "--wait", "--wait-timeout", "120", installed=True)
            write(edge / "sites" / site_source.name, site)
            write(edge / "generated/caddy.json", candidate.read_bytes())
            if migration:
                write(migration_path, json.dumps(migration))
                write(legacy_path, json.dumps(remaining))
            if old_running:
                run(["docker", "stop", old["Id"]])
            edge_changed = True
            edge_compose("up", "-d", "--wait", "--wait-timeout", "120")
            edge_compose(
                "exec", "-T", "caddy", "caddy", "reload",
                "--config", "/etc/caddy/generated/caddy.json",
            )
            if old:
                run(["docker", "rm", old["Id"]])
    except (DeployError, OSError, ValueError):
        if edge_changed and not shared_existed:
            try:
                edge_compose("stop", "caddy")
                edge_compose("rm", "-f", "caddy")
            except DeployError as error:
                print(f"Edge rollback warning: {error}", file=sys.stderr)
        for path, content in backups.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                write(path, content)
        if edge_changed:
            try:
                if shared_existed:
                    edge_compose("up", "-d", "--wait", "--wait-timeout", "120")
                    config = (
                        "/etc/caddy/generated/caddy.json"
                        if backups[edge / "generated/caddy.json"] else "/etc/caddy/Caddyfile"
                    )
                    edge_compose("exec", "-T", "caddy", "caddy", "reload", "--config", config)
                elif old_running:
                    run(["docker", "start", old["Id"]])
                    run(
                        ["docker", "exec", "-i", old["Id"], "caddy", "reload", "--config", "-"],
                        input=json.dumps(legacy),
                    )
            except DeployError as error:
                print(f"Caddy rollback failed: {error}", file=sys.stderr)
        print("The application may already have been updated; inspect it before retrying.", file=sys.stderr)
        raise
    print("Application deployed; shared Caddy is running with the updated site.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=Path.cwd())
    parser.add_argument("--edge-dir", type=Path, default=Path.home() / "edge")
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--site-file", type=Path, required=True)
    parser.add_argument("--version")
    parser.add_argument("--no-pull", action="store_true", help="Use locally built or preloaded images.")
    args = parser.parse_args()
    try:
        deploy(args)
    except (DeployError, OSError, ValueError) as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
