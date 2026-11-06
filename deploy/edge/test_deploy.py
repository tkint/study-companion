import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from deploy import DeployError, http_server, legacy_candidate, site_changes, site_id


class ConfigTests(unittest.TestCase):
    def test_conflicting_settings_fail_instead_of_overwriting(self):
        with self.assertRaises(DeployError):
            site_id(Path("bad name.caddy"))

    def test_site_api_update_changes_only_its_identified_route(self):
        first = {"@id": "edge-first", "match": [{"host": ["first.test"]}]}
        second = {"@id": "edge-second", "match": [{"host": ["second.test"]}]}
        config = {"apps": {"http": {"servers": {"srv0": {
            "listen": [":443"], "routes": [first, second],
        }}}}}
        replacement = {"@id": "edge-first", "match": [{"host": ["first.test"]}],
                       "handle": [{"handler": "static_response"}]}
        result, operations = site_changes(config, "srv0", ["first.test"], "edge-first",
                                          replacement, {}, [])
        routes = result["apps"]["http"]["servers"]["srv0"]["routes"]
        self.assertEqual(routes, [replacement, second])
        self.assertIn(("PATCH", "/id/edge-first", replacement), operations)
        self.assertNotIn(("PATCH", "/id/edge-second", second), operations)

    def test_api_creation_preserves_existing_sites(self):
        second = {"@id": "edge-second", "match": [{"host": ["second.test"]}]}
        config = {"apps": {"http": {"servers": {"srv0": {
            "listen": [":443"], "routes": [second],
        }}}}}
        route = {"@id": "edge-first", "match": [{"host": ["first.test"]}]}
        result, operations = site_changes(config, "srv0", ["first.test"], "edge-first",
                                          route, {}, [])
        routes = result["apps"]["http"]["servers"]["srv0"]["routes"]
        self.assertEqual(routes, [route, second])
        self.assertIn(("PATCH", "/config/apps/http/servers/srv0/routes", [route, second]), operations)

    def test_multi_host_route_is_rejected_without_replacing_other_hosts(self):
        existing = {"match": [{"host": ["first.test", "second.test"]}],
                    "handle": [{"handler": "static_response"}]}
        config = {"apps": {"http": {"servers": {"srv0": {
            "listen": [":443"], "routes": [existing],
        }}}}}
        route = {"@id": "edge-first", "match": [{"host": ["first.test"]}]}
        with self.assertRaises(DeployError):
            site_changes(config, "srv0", ["first.test"], "edge-first", route, {}, [])

    def test_empty_config_is_supported(self):
        name, server = http_server({})
        self.assertEqual(name, "srv0")
        self.assertEqual(server["listen"], [":443"])
        self.assertEqual(server["routes"], [])

    def test_ambiguous_or_non_caddy_port_owners_are_rejected(self):
        container = {
            "Config": {"Labels": {}, "Cmd": ["nginx"]},
            "HostConfig": {"PortBindings": {"80/tcp": [{"HostPort": "80"}]}},
            "State": {"Running": True},
        }
        with self.assertRaises(DeployError):
            legacy_candidate([container], "edge")
        container["Config"]["Cmd"] = ["caddy", "run"]
        with self.assertRaises(DeployError):
            legacy_candidate([container, copy.deepcopy(container)], "edge")
        self.assertIs(legacy_candidate([container], "edge"), container)
        container["State"]["Running"] = False
        self.assertIs(legacy_candidate([container], "edge"), container)


@unittest.skipUnless(os.environ.get("EDGE_INTEGRATION_TESTS") == "1", "Docker integration is opt-in")
class DockerDeployTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="edge-test-")
        self.root = Path(self.temporary.name)
        self.identifier = uuid.uuid4().hex[:8]
        self.project = f"edge-test-{self.identifier}"
        self.network = f"edge-network-{self.identifier}"
        self.edge_dir = self.root / "edge"
        self.edge_dir.mkdir()
        self.override = self.edge_dir / "compose.override.yaml"
        self.override.write_text(f"""name: {self.project}
services:
  caddy:
    ports: !override ["127.0.0.1::443"]
networks:
  edge:
    name: {self.network}
""")
        (self.edge_dir / "Caddyfile").write_text(
            "{\n local_certs\n}\n"
        )
        self.sources = {}
        self.apps = {}
        self.legacy = None
        self.legacy_volumes = []
        for name in ("first", "second"):
            source = self.root / f"source-{name}"
            app = self.root / f"app-{name}"
            source.mkdir()
            app.mkdir()
            (app / ".env").write_text(f"DOMAIN={name}.localhost\nEDGE_NETWORK={self.network}\n")
            (source / "compose.yaml").write_text(f"""name: app-{name}-{self.identifier}
services:
  web:
    image: caddy:2
    command: ["caddy", "respond", "--listen", ":8000", "--body", "{name}"]
    networks:
      default:
      edge:
        aliases: [{name}-upstream]
networks:
  edge:
    external: true
    name: ${{EDGE_NETWORK}}
""")
            (source / f"{name}.caddy").write_text(
                "{$DOMAIN} {\n log {\n output stdout\n }\n reverse_proxy "
                + name + "-upstream:8000\n}\n"
            )
            self.sources[name] = source
            self.apps[name] = app

    def command(self, *args, check=True):
        result = subprocess.run(args, text=True, capture_output=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def edge(self, *args, check=True):
        files = ["-f", str(self.edge_dir / "compose.yaml"), "-f", str(self.override)]
        if (self.edge_dir / "migration.compose.json").exists():
            files += ["-f", str(self.edge_dir / "migration.compose.json")]
        return self.command("docker", "compose", *files, *args, check=check)

    def app(self, name, *args):
        return self.command(
            "docker", "compose", "--project-directory", str(self.apps[name]),
            "-f", str(self.apps[name] / "compose.yaml"), *args,
        )

    def deploy(self, name, success=True):
        result = self.command(
            sys.executable, str(Path(__file__).with_name("deploy.py")),
            "--app-dir", str(self.apps[name]), "--edge-dir", str(self.edge_dir),
            "--compose-file", str(self.sources[name] / "compose.yaml"),
            "--site-file", str(self.sources[name] / f"{name}.caddy"), "--no-pull", check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def request(self, name, container=None):
        if container is None:
            container = self.edge("ps", "-q", "caddy").stdout.strip()
        last_error = None
        for _ in range(40):
            response = self.command(
                "docker", "exec", container, "curl", "--noproxy", "*", "-ksS",
                "--max-time", "2", "--resolve", f"{name}.localhost:443:127.0.0.1",
                "-D", "-", f"https://{name}.localhost/", check=False,
            )
            headers, _, body = response.stdout.partition("\n\n")
            if response.returncode == 0 and headers.splitlines()[0].split()[1] == "200":
                return body, {
                    key.lower(): value for key, value in (
                        line.split(": ", 1) for line in headers.splitlines()[1:] if ": " in line
                    )
                }
            last_error = response.stdout + response.stderr
            time.sleep(0.25)
        logs = self.command("docker", "logs", "--tail", "30", container, check=False)
        self.fail(f"Site {name} did not become available: {last_error}\n{logs.stdout}{logs.stderr}")

    def make_legacy(self, stopped=False):
        app = self.apps["first"]
        (app / "Caddyfile").write_text(
            "{\n local_certs\n}\n{$DOMAIN} {\n reverse_proxy web:8000\n}\n"
        )
        (app / "compose.yaml").write_text(f"""name: app-first-{self.identifier}
services:
  web:
    image: caddy:2
    command: ["caddy", "respond", "--listen", ":8000", "--body", "first"]
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["127.0.0.1:80:80", "127.0.0.1::443"]
    environment:
      DOMAIN: ${{DOMAIN}}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
volumes:
  caddy-data:
  caddy-config:
""")
        self.app("first", "up", "-d", "--wait")
        self.legacy = self.app("first", "ps", "-q", "caddy").stdout.strip()
        metadata = json.loads(self.command("docker", "inspect", self.legacy).stdout)[0]
        self.legacy_volumes = [
            mount["Name"] for mount in metadata["Mounts"] if mount["Type"] == "volume"
        ]
        self.assertEqual(self.request("first", self.legacy)[0], "first")
        self.command("docker", "exec", self.legacy, "sh", "-c", "echo retained >/data/deploy-marker")
        if stopped:
            self.app("first", "stop", "caddy")

    def tearDown(self):
        if (self.edge_dir / "compose.yaml").exists():
            self.edge("down", "-v")
        for name in self.apps:
            self.command(
                "docker", "compose", "--project-directory", str(self.apps[name]),
                "-f", str(self.sources[name] / "compose.yaml"),
                "down", "-v", "--remove-orphans",
            )
        existing = self.command("docker", "volume", "ls", "--format", "{{.Name}}").stdout.splitlines()
        for volume in self.legacy_volumes:
            if volume in existing:
                self.command("docker", "volume", "rm", volume)
        networks = self.command("docker", "network", "ls", "--format", "{{.Name}}").stdout.splitlines()
        if self.network in networks:
            self.command("docker", "network", "rm", self.network)
        self.temporary.cleanup()

    def test_fresh_existing_stopped_edge_and_missing_apps(self):
        self.deploy("first")
        self.assertEqual(self.request("first")[0], "first")
        self.deploy("second")
        self.assertEqual(self.request("second")[0], "second")
        first_site = self.sources["first"] / "first.caddy"
        first_site.write_text("{$DOMAIN} {\n header X-Deployment running\n reverse_proxy first-upstream:8000\n}\n")
        self.deploy("first")
        self.assertEqual(self.request("first")[1]["x-deployment"], "running")
        self.edge("stop", "caddy")
        site = self.sources["second"] / "second.caddy"
        site.write_text("{$DOMAIN} {\n header X-Deployment updated\n reverse_proxy second-upstream:8000\n}\n")
        self.deploy("second")
        self.assertEqual(self.request("second")[1]["x-deployment"], "updated")
        self.app("first", "down")
        self.assertEqual(self.request("second")[0], "second")
        self.deploy("first")
        self.app("second", "down")
        self.assertEqual(self.request("first")[0], "first")

    def test_removed_edge_container_resumes_the_autosaved_api_config(self):
        self.deploy("first")
        self.deploy("second")
        self.edge("stop", "caddy")
        self.edge("rm", "-f", "caddy")
        self.deploy("second")
        self.assertEqual(self.request("first")[0], "first")
        self.assertEqual(self.request("second")[0], "second")

    def test_invalid_site_preserves_existing_sites(self):
        self.deploy("first")
        container = self.edge("ps", "-q", "caddy").stdout.strip()
        before = self.command("docker", "exec", container, "curl", "-fsS",
                              "http://127.0.0.1:2019/config/").stdout
        (self.sources["second"] / "second.caddy").write_text("{$DOMAIN} {\n invalid_directive\n}\n")
        self.deploy("second", success=False)
        after = self.command("docker", "exec", container, "curl", "-fsS",
                             "http://127.0.0.1:2019/config/").stdout
        self.assertEqual(after, before)
        self.assertFalse((self.edge_dir / "sites/second.caddy").exists())
        self.assertEqual(self.request("first")[0], "first")

    def test_concurrent_deployments_preserve_both_sites(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(self.deploy, ("first", "second")))
        self.assertEqual(self.request("first")[0], "first")
        self.assertEqual(self.request("second")[0], "second")

    def test_remote_upload_and_quoted_paths(self):
        checkout = self.root / "checkout"
        shutil.copytree(Path(__file__).parent, checkout / "deploy/edge")
        shutil.copytree(self.sources["first"], checkout / "source-first")
        tools = self.root / "tools"
        tools.mkdir()
        ssh = tools / "ssh"
        ssh.write_text(
            "#!/usr/bin/env python3\nimport shlex, subprocess, sys\n"
            "sys.exit(subprocess.run(shlex.split(sys.argv[-1])).returncode)\n"
        )
        ssh.chmod(0o700)
        edge = self.root / "edge with spaces"
        self.edge_dir.rename(edge)
        self.edge_dir = edge
        self.override = edge / "compose.override.yaml"
        environment = dict(os.environ, SSH_KEY="test-key", HOST="localhost", SSH_USER="test",
                           HOST_KEY="test-host-key", DEPLOY_DIR=str(self.apps["first"]),
                           EDGE_DIR=str(edge), VERSION="latest", PATH=f"{tools}:{os.environ['PATH']}")
        result = subprocess.run(
            ["bash", "deploy/edge/remote-deploy.sh", "source-first/compose.yaml", "source-first/first.caddy"],
            cwd=checkout, env=environment, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.request("first")[0], "first")

    def check_migration(self, stopped):
        self.make_legacy(stopped=stopped)
        self.deploy("second")
        self.assertEqual(self.request("first")[0], "first")
        self.assertEqual(self.request("second")[0], "second")
        self.assertEqual(self.edge("exec", "-T", "caddy", "cat", "/data/deploy-marker").stdout.strip(), "retained")
        migration = json.loads((self.edge_dir / "migration.compose.json").read_text())
        self.assertIn(migration["volumes"]["caddy-data"]["name"], self.legacy_volumes)
        self.deploy("first")
        self.assertEqual(self.request("first")[0], "first")
        self.assertEqual(self.request("second")[0], "second")
        migration = json.loads((self.edge_dir / "migration.compose.json").read_text())
        self.assertNotIn("networks", migration)

    def test_running_legacy_is_migrated(self):
        self.check_migration(stopped=False)

    def test_stopped_legacy_is_migrated(self):
        self.check_migration(stopped=True)

    def test_legacy_proxy_owned_by_target_app_is_migrated(self):
        self.make_legacy()
        self.deploy("first")
        self.assertEqual(self.request("first")[0], "first")
        self.assertEqual(self.edge("exec", "-T", "caddy", "cat", "/data/deploy-marker").stdout.strip(), "retained")

    def test_failed_migration_restarts_original_caddy(self):
        self.make_legacy()
        self.override.write_text(self.override.read_text().replace(
            '    ports: !override ["127.0.0.1::443"]',
            '    ports: !override ["127.0.0.1::443"]\n    command: ["caddy", "version"]',
        ))
        self.deploy("second", success=False)
        metadata = json.loads(self.command("docker", "inspect", self.legacy).stdout)[0]
        self.assertTrue(metadata["State"]["Running"])
        config = json.loads(self.command(
            "docker", "exec", self.legacy, "curl", "-fsS", "http://127.0.0.1:2019/config/"
        ).stdout)
        self.assertIn("first.localhost", json.dumps(config))


if __name__ == "__main__":
    unittest.main()
