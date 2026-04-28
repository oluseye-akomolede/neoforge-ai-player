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


@dataclass
class TestWorld:
    name: str
    namespace: str = NAMESPACE
    pod_name: str = ""
    mod_api_url: str = ""
    agent_api_url: str = ""
    ready: bool = False

    def __post_init__(self):
        self.pod_name = f"test-world-{self.name}"


def _kubectl(*args, capture=True) -> subprocess.CompletedProcess:
    cmd = ["kubectl"] + list(args)
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=30)


def _load_template() -> dict:
    with open(TEMPLATE_PATH) as f:
        return yaml.safe_load(f)


def create_world(name: str, ttl: int = DEFAULT_TTL) -> TestWorld:
    world = TestWorld(name=name)
    pod = _load_template()

    pod["metadata"]["name"] = world.pod_name
    pod["metadata"]["annotations"]["test-world/ttl"] = str(ttl)

    manifest = yaml.dump(pod)
    result = _kubectl("apply", "-n", world.namespace, "-f", "-", capture=True)
    proc = subprocess.run(
        ["kubectl", "apply", "-n", world.namespace, "-f", "-"],
        input=manifest, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to create pod: {proc.stderr}")

    print(f"[test-world] Created pod {world.pod_name}")
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
