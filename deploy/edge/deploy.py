#!/usr/bin/env python3
"""Deploy one application and reconcile the host's shared Caddy."""

import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote


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


def has_proxy(value):
    if isinstance(value, dict):
        return value.get("handler") == "reverse_proxy" or any(has_proxy(item) for item in value.values())
    return isinstance(value, list) and any(has_proxy(item) for item in value)


def has_legacy_proxy(config):
    servers = config.get("apps", {}).get("http", {}).get("servers", {})
    return any(
        not route.get("@id", "").startswith("edge-") and has_proxy(route)
        for server in servers.values()
        for route in server.get("routes", [])
    )


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


def http_server(config):
    servers = config.setdefault("apps", {}).setdefault("http", {}).setdefault("servers", {})
    server_name = next(
        (name for name, value in servers.items()
         if any(address.rsplit(":", 1)[-1] == "443" for address in value.get("listen", []))),
        None,
    )
    if server_name is None:
        server_name = next(iter(servers), "srv0")
    server = servers.setdefault(server_name, {"listen": [":443"]})
    server.setdefault("routes", [])
    return server_name, server


def site_id(site_file):
    name = site_file.stem
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise DeployError(f"Site filename {site_file.name!r} cannot form a safe Caddy ID.")
    return f"edge-{name}"


def adapt_file(path, image, *, env=None, extra_mounts=()):
    command = ["docker", "run", "--rm"]
    for source, target in extra_mounts:
        command += ["-v", f"{source}:{target}:ro"]
    command += ["-v", f"{path}:/etc/caddy/site.caddy:ro"]
    for key, value in (env or {}).items():
        command += ["-e", f"{key}={value}"]
    command += [image, "caddy", "adapt", "--config", "/etc/caddy/site.caddy"]
    return json.loads(run(command))


def make_site(adapted, domains, identifier):
    _, server = http_server(adapted)
    routes = copy.deepcopy(server.get("routes", []))
    if not routes:
        raise DeployError(f"The Caddyfile for {domain} did not adapt to any HTTP routes.")
    route = {
        "@id": identifier,
        "match": [{"host": domains}],
        "handle": [{"handler": "subroute", "routes": routes}],
        "terminal": True,
    }

    log_config = adapted.get("logging", {}).get("logs", {})
    logs = {}
    for name, value in log_config.items():
        if name == "default":
            continue
        unique_name = f"{identifier}-{name}"
        logs[unique_name] = copy.deepcopy(value)
        default = logs[unique_name].get("include")
        if default:
            logs[unique_name]["include"] = [
                item.replace(f".{name}", f".{unique_name}") for item in default
            ]
    logger_names = sorted({
        f"{identifier}-{name}"
        for domain in domains
        for name in server.get("logs", {}).get("logger_names", {}).get(domain, [])
    })
    return route, logs, logger_names


def route_hosts(route):
    hosts = set()
    for matcher in route.get("match", []):
        hosts.update(matcher.get("host", []))
    return hosts


def site_changes(config, server_name, domains, identifier, route, logs, logger_names):
    config = copy.deepcopy(config)
    server_name, server = http_server(config)
    routes = server["routes"]
    managed_hosts = set(domains)
    same_id = next(
        (index for index, item in enumerate(routes) if item.get("@id") == identifier), None
    )
    matching = [index for index, item in enumerate(routes) if managed_hosts & route_hosts(item)]
    selected = same_id if same_id is not None else (matching[0] if matching else None)
    old_hosts = route_hosts(routes[selected]) if selected is not None else set()
    if selected is not None and route_hosts(routes[selected]) - managed_hosts:
        raise DeployError(
            "The existing site route also serves other hostnames; split that route before updating this site."
        )
    route_operations = []

    if selected is None:
        routes.insert(0, route)
        route_operations.append((
            "PATCH", f"/config/apps/http/servers/{server_name}/routes", routes
        ))
    else:
        routes[selected] = route
        old = (
            ("PATCH", f"/id/{identifier}", route)
            if same_id is not None
            else ("PATCH", f"/config/apps/http/servers/{server_name}/routes/{selected}", route)
        )
        route_operations.append(old)

    for index in reversed(matching):
        if index == selected:
            continue
        remaining = without_hosts(routes[index], managed_hosts)
        if remaining is None:
            del routes[index]
            route_operations.append(
                ("DELETE", f"/config/apps/http/servers/{server_name}/routes/{index}", None)
            )
        else:
            routes[index] = remaining
            route_id = remaining.get("@id")
            route_operations.append(
                ("PATCH", f"/id/{route_id}" if route_id else
                 f"/config/apps/http/servers/{server_name}/routes/{index}", remaining)
            )

    operations = []
    current_logs = config.setdefault("logging", {}).setdefault("logs", {})
    default_existed = "default" in current_logs
    default = current_logs.setdefault("default", {})
    exclude_existed = "exclude" in default
    excluded = default.setdefault("exclude", [])
    access_loggers = []
    for name, value in logs.items():
        existed = name in current_logs
        current_logs[name] = copy.deepcopy(value)
        operations.insert(0, (
            "PATCH" if existed else "PUT",
            f"/config/logging/logs/{name}", value,
        ))
        access_logger = next(
            (item.rsplit(".", 1)[-1] for item in value.get("include", [])
             if item.startswith("http.log.access.")), None,
        )
        if access_logger:
            access_loggers.append(f"http.log.access.{access_logger}")

    new_excludes = [name for name in access_loggers if name not in excluded]
    if not default_existed and new_excludes:
        operations.insert(0, ("PUT", "/config/logging/logs/default", {"exclude": new_excludes}))
        excluded.extend(new_excludes)
    elif not exclude_existed and new_excludes:
        operations.insert(0, ("PUT", "/config/logging/logs/default/exclude", new_excludes))
        excluded.extend(new_excludes)
    else:
        for name in new_excludes:
            operations.insert(0, ("POST", "/config/logging/logs/default/exclude", name))
            excluded.append(name)

    names = server.setdefault("logs", {}).setdefault("logger_names", {})
    for domain in sorted(old_hosts - managed_hosts):
        if domain in names:
            del names[domain]
            operations.append((
                "DELETE",
                f"/config/apps/http/servers/{server_name}/logs/logger_names/{quote(domain, safe='')}",
                None,
            ))
    for domain in domains:
        existed = domain in names
        names[domain] = logger_names
        operations.append((
            "PATCH" if existed else "PUT",
            f"/config/apps/http/servers/{server_name}/logs/logger_names/{quote(domain, safe='')}",
            logger_names,
        ))
    operations.extend(route_operations)
    return config, operations


def api_request(compose, method, path, value=None, *, expected=(200,)):
    command = [
        "docker", "compose", *compose, "exec", "-T", "caddy", "curl",
        "--silent", "--show-error", "-w", "\n%{http_code}",
        "-X", method, f"http://127.0.0.1:2019{path}",
    ]
    payload = value
    if isinstance(value, str):
        payload = json.dumps(value)
    if payload is not None:
        command += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
    result = subprocess.run(command, input=payload if isinstance(payload, str) else
                            (json.dumps(payload) if payload is not None else None),
                            text=True, capture_output=True)
    if result.returncode:
        raise DeployError(f"Caddy API request failed:\n{result.stderr.strip()}")
    body, separator, status_text = result.stdout.rpartition("\n")
    if not separator or int(status_text) not in expected:
        raise DeployError(
            f"Caddy API {method} {path} returned {status_text or 'no status'}: {body.strip()}"
        )
    if method == "GET":
        return json.loads(body) if body else {}
    return body


def edge_compose_args(edge):
    files = ["--project-directory", str(edge), "-f", str(edge / "compose.yaml")]
    for name in ("compose.override.yaml", "migration.compose.json"):
        if (edge / name).exists():
            files += ["-f", str(edge / name)]
    return files


def api_apply(compose, operations):
    for method, path, value in operations:
        api_request(compose, method, path, value, expected=(200, 201, 202, 204))


def config_has_autosave(volume_name, image):
    volumes = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines()
    if volume_name not in volumes:
        return False
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{volume_name}:/config:ro", image,
         "sh", "-c", "test -s /config/caddy/autosave.json"],
        text=True, capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise DeployError(f"Could not inspect saved Caddy configuration:\n{result.stderr.strip()}")
    return result.returncode == 0


def write_bootstrap(config, edge, image):
    _, server = http_server(config)
    server["listen"] = [":443"]
    server.setdefault("logs", {}).setdefault("logger_names", {})
    config.setdefault("admin", {})
    if config["admin"].get("disabled"):
        raise DeployError("Caddy admin API is disabled; site deployment needs the local admin API.")
    listen = config["admin"].get("listen")
    if listen and not listen.startswith(("localhost:", "127.0.0.1:")):
        raise DeployError("Caddy admin API must listen on localhost only.")
    config.setdefault("logging", {}).setdefault("logs", {}).setdefault("default", {}).setdefault(
        "exclude", []
    )
    path = edge / "generated/bootstrap.json"
    write(path, json.dumps(config))
    validate = [
        "docker", "run", "--rm", "-v", f"{path}:/tmp/bootstrap.json:ro",
        image, "caddy", "validate", "--config", "/tmp/bootstrap.json",
    ]
    run(validate)


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
        edge / "compose.yaml", edge / "Caddyfile", edge / "generated/bootstrap.json",
        edge / "migration.compose.json", edge / "sites" / site_source.name,
        app / compose_source.name,
    ]
    backups = {path: path.read_bytes() if path.exists() else None for path in targets}
    old = None
    old_running = False
    edge_changed = False
    shared_existed = False
    api_changed = False
    migration = None
    image = "caddy:2"

    def edge_compose(*command):
        files = ["-f", str(edge / "compose.yaml")]
        return run(["docker", "compose", "--project-directory", str(edge),
                    *edge_compose_args(edge)[2:], *command], cwd=edge, env=edge_env)

    try:
        write(edge / "compose.yaml", (source / "compose.yaml").read_bytes())
        if not (edge / "Caddyfile").exists():
            write(edge / "Caddyfile", (source / "Caddyfile").read_bytes())
        (edge / "sites").mkdir(parents=True, exist_ok=True)
        migration_path = edge / "migration.compose.json"
        migration = json.loads(migration_path.read_text()) if migration_path.exists() else None
        if migration:
            migration.get("volumes", {}).pop("caddy-config", None)
            migration["volumes"] = {
                key: value for key, value in migration.get("volumes", {}).items()
                if key == "caddy-data"
            }
            write(migration_path, json.dumps(migration))
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
        if not shared_existed:
            old = legacy_candidate(containers, project)
            if old:
                if migration:
                    raise DeployError("Legacy migration state already exists; refusing to overwrite it.")
                legacy, migration = export_legacy(old, containers)
                legacy_domains = {domain}
                legacy = without_hosts(legacy, legacy_domains)
                old_running = old["State"]["Running"]
                write(migration_path, json.dumps(migration))
                edge_config = json.loads(edge_compose("config", "--format", "json"))
        config_volume = edge_config["volumes"]["caddy-config"]["name"]
        bootstrap_required = not config_has_autosave(config_volume, image)
        if bootstrap_required:
            if old:
                bootstrap = legacy
            else:
                with tempfile.TemporaryDirectory(prefix=".bootstrap-", dir=edge) as temporary:
                    empty_sites = Path(temporary) / "sites"
                    empty_sites.mkdir()
                    root_config = adapt_file(
                        edge / "Caddyfile", image,
                        extra_mounts=((empty_sites, "/etc/caddy/sites"),),
                    )
                bootstrap = root_config
            write_bootstrap(bootstrap, edge, image)
        if migration:
            if old:
                remaining = legacy
            else:
                remaining = json.loads(
                    run(["docker", "run", "--rm", "-v", f"{config_volume}:/config:ro",
                         image, "sh", "-c", "cat /config/caddy/autosave.json"])
                )
            if not has_legacy_proxy(remaining):
                migration.pop("networks", None)
                migration["services"]["caddy"]["networks"] = ["edge"]
        else:
            remaining = {}

        write(app / compose_source.name, compose_source.read_bytes())
        app_compose("up", "-d", "--wait", "--wait-timeout", "120", installed=True)
        write(edge / "sites" / site_source.name, site)
        if migration:
            write(migration_path, json.dumps(migration))
        if old_running:
            run(["docker", "stop", old["Id"]])
        edge_changed = True
        edge_compose("up", "-d", "--wait", "--wait-timeout", "120")

        compose_args = edge_compose_args(edge)
        api_config = api_request(compose_args, "GET", "/config/")
        sites = []
        if bootstrap_required:
            sites = [
                path for path in sorted((edge / "sites").glob("*.caddy"))
                if path.name != site_source.name
            ]
        sites.append(edge / "sites" / site_source.name)
        for path in sites:
            if path.name == site_source.name:
                site_domains = [domain]
                adapted = adapt_file(path, image)
            else:
                adapted = adapt_file(path, image)
                site_domains = sorted(site_hosts(adapted))
                if not site_domains:
                    raise DeployError(f"{path.name} did not adapt to a site with host matchers.")
            identifier = site_id(path)
            route, logs, logger_names = make_site(adapted, site_domains, identifier)
            server_name, _ = http_server(api_config)
            candidate, operations = site_changes(
                api_config, server_name, site_domains, identifier, route, logs, logger_names
            )
            with tempfile.TemporaryDirectory(prefix=".validate-", dir=edge) as temporary:
                candidate_path = Path(temporary) / "candidate.json"
                write(candidate_path, json.dumps(candidate))
                validation = [
                    "docker", "run", "--rm", "-v", f"{candidate_path}:/tmp/candidate.json:ro",
                    image, "caddy", "validate", "--config", "/tmp/candidate.json",
                ]
                run(validation)
            for operation in operations:
                api_apply(compose_args, [operation])
                api_changed = True
            api_config = candidate
        if migration and "networks" in migration and not has_legacy_proxy(api_config):
            migration.pop("networks")
            migration["services"]["caddy"]["networks"] = ["edge"]
            write(migration_path, json.dumps(migration))
            edge_compose("up", "-d", "--wait", "--wait-timeout", "120")
        if old:
            run(["docker", "rm", old["Id"]])
    except (DeployError, OSError, ValueError):
        if api_changed and not old:
            print("Caddy accepted an API update; its autosaved configuration remains active.", file=sys.stderr)
            raise
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
                elif old_running:
                    run(["docker", "start", old["Id"]])
            except DeployError as error:
                print(f"Caddy rollback failed: {error}", file=sys.stderr)
        print("The application may already have been updated; inspect it before retrying.", file=sys.stderr)
        raise
    print("Application deployed; shared Caddy is running with the updated site.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=Path.cwd())
    parser.add_argument("--edge-dir", type=Path, default=Path.home() / "caddy")
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
