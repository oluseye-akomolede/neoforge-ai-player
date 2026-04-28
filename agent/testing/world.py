"""Test world lifecycle — create, wait, and tear down ephemeral NeoForge pods."""

import json
import subprocess
import time
import yaml
from pathlib import Path
from dataclasses import dataclass, field

TEMPLATE_PATH = Path(__file__).resolve().parent / "pod-template.yaml"
NAMESPACE = "minecraft-test"
DEFAULT_TTL = 1800

PG_HOST = "pgvector.minecraft-test.svc.cluster.local"
PG_PORT = "5432"
PG_USER = "aibot"
PG_PASSWORD = "aibot-memory-2026"

WORLD_TYPE_ENV: dict[str, dict[str, str]] = {
    "flat": {},
    "normal": {
        "LEVEL_TYPE": "minecraft:normal",
        "SPAWN_ANIMALS": "true",
    },
}


@dataclass
class TestWorld:
    name: str
    namespace: str = NAMESPACE
    pod_name: str = ""
    mod_api_url: str = ""
    agent_api_url: str = ""
    ready: bool = False
    test_db: str = ""

    def __post_init__(self):
        self.pod_name = f"test-world-{self.name}"
        self.test_db = f"botmemory_test_{self.name.replace('-', '_')}"


def _kubectl(*args, capture=True) -> subprocess.CompletedProcess:
    cmd = ["kubectl"] + list(args)
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=30)


def _psql(sql: str, db: str = "botmemory") -> subprocess.CompletedProcess:
    """Run SQL against the pgvector instance via kubectl exec."""
    return subprocess.run(
        ["kubectl", "exec", "-n", NAMESPACE, "deploy/pgvector", "--",
         "psql", "-U", PG_USER, "-d", db, "-c", sql],
        capture_output=True, text=True, timeout=30,
    )


def _load_template() -> dict:
    with open(TEMPLATE_PATH) as f:
        return yaml.safe_load(f)


def _patch_container_env(pod: dict, container_name: str, overrides: dict[str, str]):
    """Override env vars for a named container in-place."""
    for container in pod["spec"]["containers"]:
        if container["name"] == container_name:
            for entry in container.get("env", []):
                name = entry.get("name")
                if name in overrides and "value" in entry:
                    entry["value"] = overrides[name]
            break


def create_test_db(world: "TestWorld"):
    """Create an isolated temporary database for a test world."""
    db = world.test_db
    _psql(f"DROP DATABASE IF EXISTS {db};")
    result = _psql(f"CREATE DATABASE {db} OWNER {PG_USER};")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create test DB {db}: {result.stderr}")
    _psql("CREATE EXTENSION IF NOT EXISTS vector;", db=db)
    print(f"[test-world] Created temp database: {db}")


def drop_test_db(world: "TestWorld"):
    """Drop the temporary test database."""
    db = world.test_db
    _psql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db}';")
    result = _psql(f"DROP DATABASE IF EXISTS {db};")
    if result.returncode == 0:
        print(f"[test-world] Dropped temp database: {db}")
    else:
        print(f"[test-world] Warning: failed to drop {db}: {result.stderr}")


def _test_dsn(world: "TestWorld") -> str:
    return f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{world.test_db}"


def create_world(
    name: str,
    ttl: int = DEFAULT_TTL,
    world_type: str = "flat",
    world_settings: dict[str, str] | None = None,
) -> TestWorld:
    world = TestWorld(name=name)
    pod = _load_template()

    pod["metadata"]["name"] = world.pod_name
    pod["metadata"]["annotations"]["test-world/ttl"] = str(ttl)

    # World type env overrides for mc-server
    env_overrides = WORLD_TYPE_ENV.get(world_type, {}).copy()
    if world_settings:
        for k, v in world_settings.items():
            env_overrides[k.upper()] = str(v)
    if env_overrides:
        _patch_container_env(pod, "mc-server", env_overrides)

    # Isolated database for this test world
    create_test_db(world)
    _patch_container_env(pod, "agent", {"PG_DSN": _test_dsn(world)})

    manifest = yaml.dump(pod)
    proc = subprocess.run(
        ["kubectl", "apply", "-n", world.namespace, "-f", "-"],
        input=manifest, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        drop_test_db(world)
        raise RuntimeError(f"Failed to create pod: {proc.stderr}")

    print(f"[test-world] Created pod {world.pod_name} (type={world_type}, db={world.test_db})")
    return world


def wait_ready(world: TestWorld, timeout: int = 300) -> bool:
    print(f"[test-world] Waiting for {world.pod_name} to be ready (timeout={timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _kubectl(
            "get", "pod", world.pod_name, "-n", world.namespace,
            "-o", "jsonpath={.status.containerStatuses[*].ready}",
        )
        statuses = result.stdout.strip().split()
        if len(statuses) >= 2 and all(s == "true" for s in statuses):
            world.ready = True
            world.mod_api_url = f"http://{world.pod_name}.{world.namespace}.svc.cluster.local:3100"
            world.agent_api_url = f"http://{world.pod_name}.{world.namespace}.svc.cluster.local:5000"
            print(f"[test-world] {world.pod_name} is ready")
            return True

        result = _kubectl(
            "get", "pod", world.pod_name, "-n", world.namespace,
            "-o", "jsonpath={.status.phase}",
        )
        phase = result.stdout.strip()
        if phase in ("Failed", "Unknown"):
            print(f"[test-world] Pod entered {phase} state")
            return False

        time.sleep(10)

    print(f"[test-world] Timed out waiting for {world.pod_name}")
    return False


def destroy_world(world: TestWorld) -> bool:
    print(f"[test-world] Destroying {world.pod_name}...")
    result = _kubectl(
        "delete", "pod", world.pod_name, "-n", world.namespace,
        "--grace-period=10", "--ignore-not-found",
    )
    if world.test_db:
        drop_test_db(world)
    return result.returncode == 0


def get_pod_ip(world: TestWorld) -> str | None:
    result = _kubectl(
        "get", "pod", world.pod_name, "-n", world.namespace,
        "-o", "jsonpath={.status.podIP}",
    )
    ip = result.stdout.strip()
    return ip if ip else None


def get_logs(world: TestWorld, container: str = "agent", tail: int = 100) -> str:
    result = _kubectl(
        "logs", world.pod_name, "-n", world.namespace,
        "-c", container, f"--tail={tail}",
    )
    return result.stdout


def list_worlds() -> list[dict]:
    result = _kubectl(
        "get", "pods", "-n", NAMESPACE, "-l", "test-world=true",
        "-o", "json",
    )
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    worlds = []
    for item in data.get("items", []):
        meta = item["metadata"]
        status = item.get("status", {})
        worlds.append({
            "name": meta["name"],
            "phase": status.get("phase", "Unknown"),
            "created": meta.get("creationTimestamp", ""),
            "ttl": meta.get("annotations", {}).get("test-world/ttl", "1800"),
        })
    return worlds
