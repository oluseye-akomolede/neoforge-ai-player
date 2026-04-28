"""Test harness — runs bot behavior tests against ephemeral test worlds."""

import json
import time
import requests
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .world import TestWorld, create_world, wait_ready, destroy_world, get_logs, get_pod_ip


@dataclass
class TestStep:
    instruction: str
    timeout: int = 120
    success: dict = field(default_factory=dict)


@dataclass
class TestDefinition:
    name: str
    world_type: str = "flat"
    world_seed: str | None = None
    bots: list[dict] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    ttl: int = 1800


@dataclass
class StepResult:
    step: str
    passed: bool
    duration: float
    details: dict = field(default_factory=dict)


@dataclass
class TestResult:
    test_name: str
    passed: bool
    duration: float
    step_results: list[StepResult] = field(default_factory=list)
    error: str | None = None
    logs: str = ""


def load_test(path: Path) -> TestDefinition:
    with open(path) as f:
        raw = yaml.safe_load(f)

    steps = []
    for s in raw.get("steps", []):
        steps.append(TestStep(
            instruction=s["instruction"],
            timeout=s.get("timeout", 120),
            success=s.get("success", {}),
        ))

    return TestDefinition(
        name=raw["name"],
        world_type=raw.get("world", {}).get("type", "flat"),
        world_seed=raw.get("world", {}).get("seed"),
        bots=raw.get("bots", [{"image": None}]),
        steps=steps,
        ttl=raw.get("ttl", 1800),
    )


class TestRunner:
    def __init__(self, registry_url: str | None = None, registry_key: str | None = None):
        self.registry_url = registry_url
        self.registry_key = registry_key

    def _api_get(self, base_url: str, path: str, timeout: int = 10) -> dict:
        r = requests.get(f"{base_url}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()

    def _api_post(self, base_url: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
        r = requests.post(f"{base_url}{path}", json=body or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def _wait_mod_api(self, world: TestWorld, timeout: int = 120) -> bool:
        ip = get_pod_ip(world)
        if not ip:
            return False
        base = f"http://{ip}:3100"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = requests.get(f"{base}/health", timeout=5)
                if r.status_code == 200:
                    world.mod_api_url = base
                    world.agent_api_url = f"http://{ip}:5000"
                    return True
            except (requests.ConnectionError, requests.Timeout):
                pass
            time.sleep(5)
        return False

    def _check_success(self, criteria: dict, world: TestWorld, bot_name: str) -> tuple[bool, dict]:
        details: dict[str, Any] = {}

        if "inventory_contains" in criteria:
            inv_check = criteria["inventory_contains"]
            item = inv_check["item"]
            min_count = inv_check.get("min_count", 1)
            try:
                inv = self._api_get(world.mod_api_url, f"/bot/{bot_name}/inventory")
                items = inv.get("inventory", inv.get("items", []))
                total = sum(
                    slot.get("count", 0)
                    for slot in items
                    if item in slot.get("item", "")
                )
                details["expected"] = f">= {min_count} {item}"
                details["actual"] = f"{total} {item}"
                return total >= min_count, details
            except Exception as e:
                details["error"] = str(e)
                return False, details

        if "bot_status" in criteria:
            check = criteria["bot_status"]
            try:
                status = self._api_get(world.mod_api_url, f"/bot/{bot_name}/status")
                for key, expected in check.items():
                    actual = status.get(key)
                    if actual != expected:
                        details[f"{key}_expected"] = expected
                        details[f"{key}_actual"] = actual
                        return False, details
                return True, details
            except Exception as e:
                details["error"] = str(e)
                return False, details

        if "directive_completed" in criteria:
            try:
                brain = self._api_get(world.mod_api_url, f"/bot/{bot_name}/brain")
                directive = brain.get("directive", brain.get("last_directive", {}))
                status = directive.get("status", "")
                details["directive_status"] = status
                return status.upper() == "COMPLETED", details
            except Exception as e:
                details["error"] = str(e)
                return False, details

        return True, {"note": "no criteria specified"}

    def run_test(self, test_def: TestDefinition) -> TestResult:
        start = time.time()
        world = None
        try:
            world = create_world(test_def.name, ttl=test_def.ttl)

            if not wait_ready(world, timeout=300):
                return TestResult(
                    test_name=test_def.name, passed=False,
                    duration=time.time() - start,
                    error="Test world pod failed to become ready",
                )

            if not self._wait_mod_api(world, timeout=120):
                return TestResult(
                    test_name=test_def.name, passed=False,
                    duration=time.time() - start,
                    error="Mod API never became reachable",
                    logs=get_logs(world, "mc-server", 50),
                )

            time.sleep(5)

            bot_name = None
            for bot_def in test_def.bots:
                try:
                    bots = self._api_get(world.mod_api_url, "/bots")
                    bot_list = bots.get("bots", [])
                    if bot_list:
                        if isinstance(bot_list[0], dict):
                            bot_name = bot_list[0]["name"]
                        else:
                            bot_name = bot_list[0]
                except Exception:
                    pass

            if not bot_name:
                return TestResult(
                    test_name=test_def.name, passed=False,
                    duration=time.time() - start,
                    error="No bots available in test world",
                    logs=get_logs(world, "agent", 50),
                )

            step_results = []
            all_passed = True

            for step in test_def.steps:
                step_start = time.time()
                print(f"[harness] Running step: {step.instruction}")

                try:
                    self._api_post(
                        world.agent_api_url, "/api/command",
                        {"bot": bot_name, "message": step.instruction},
                    )
                except Exception as e:
                    sr = StepResult(
                        step=step.instruction, passed=False,
                        duration=time.time() - step_start,
                        details={"error": f"Failed to send instruction: {e}"},
                    )
                    step_results.append(sr)
                    all_passed = False
                    continue

                passed = False
                details: dict[str, Any] = {}
                deadline = time.time() + step.timeout

                while time.time() < deadline:
                    time.sleep(5)
                    passed, details = self._check_success(
                        step.success, world, bot_name,
                    )
                    if passed:
                        break

                sr = StepResult(
                    step=step.instruction, passed=passed,
                    duration=time.time() - step_start,
                    details=details,
                )
                step_results.append(sr)
                if not passed:
                    all_passed = False

            logs = get_logs(world, "agent", 100)

            return TestResult(
                test_name=test_def.name, passed=all_passed,
                duration=time.time() - start,
                step_results=step_results,
                logs=logs,
            )

        except Exception as e:
            return TestResult(
                test_name=test_def.name, passed=False,
                duration=time.time() - start,
                error=str(e),
            )
        finally:
            if world:
                destroy_world(world)


def run_tests(test_paths: list[Path], **runner_kwargs) -> list[TestResult]:
    runner = TestRunner(**runner_kwargs)
    results = []
    for path in test_paths:
        test_def = load_test(path)
        print(f"\n{'='*60}")
        print(f"Running test: {test_def.name}")
        print(f"{'='*60}")
        result = runner.run_test(test_def)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.test_name} ({result.duration:.1f}s)")
        for sr in result.step_results:
            s = "PASS" if sr.passed else "FAIL"
            print(f"  [{s}] {sr.step} ({sr.duration:.1f}s) {sr.details}")
        if result.error:
            print(f"  ERROR: {result.error}")
    return results
