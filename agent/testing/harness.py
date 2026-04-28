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
    phase: str = ""
    bot: str = ""


@dataclass
class TestDefinition:
    name: str
    description: str = ""
    goal: str = ""
    world_type: str = "flat"
    world_settings: dict = field(default_factory=dict)
    bots: list[dict] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    ttl: int = 1800
    halt_on_failure: bool = False


@dataclass
class StepResult:
    step: str
    passed: bool
    duration: float
    details: dict = field(default_factory=dict)
    phase: str = ""


@dataclass
class TestResult:
    test_name: str
    passed: bool
    duration: float
    step_results: list[StepResult] = field(default_factory=list)
    error: str | None = None
    logs: str = ""
    phases_completed: int = 0
    phases_total: int = 0


def load_test(path: Path) -> TestDefinition:
    with open(path) as f:
        raw = yaml.safe_load(f)

    steps = []
    for s in raw.get("steps", []):
        steps.append(TestStep(
            instruction=s["instruction"],
            timeout=s.get("timeout", 120),
            success=s.get("success", {}),
            phase=s.get("phase", ""),
            bot=s.get("bot", ""),
        ))

    world_cfg = raw.get("world", {})
    settings = world_cfg.get("settings", {})
    seed = world_cfg.get("seed")
    if seed:
        settings.setdefault("seed", str(seed))

    return TestDefinition(
        name=raw["name"],
        description=raw.get("description", ""),
        goal=raw.get("goal", ""),
        world_type=world_cfg.get("type", "flat"),
        world_settings=settings,
        bots=raw.get("bots", [{"image": None}]),
        steps=steps,
        ttl=raw.get("ttl", 1800),
        halt_on_failure=raw.get("halt_on_failure", False),
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

    def _get_all_bots(self, world: TestWorld) -> list[str]:
        try:
            resp = self._api_get(world.mod_api_url, "/bots")
            bot_list = resp.get("bots", [])
            return [b["name"] if isinstance(b, dict) else b for b in bot_list]
        except Exception:
            return []

    def _check_success(self, criteria: dict, world: TestWorld, bot_name: str) -> tuple[bool, dict]:
        details: dict[str, Any] = {}

        if "inventory_contains" in criteria:
            inv_check = criteria["inventory_contains"]
            item = inv_check["item"]
            min_count = inv_check.get("min_count", 1)
            try:
                all_bots = self._get_all_bots(world)
                total = 0
                holder = ""
                for bot in all_bots:
                    inv = self._api_get(world.mod_api_url, f"/bot/{bot}/inventory")
                    items = inv.get("inventory", inv.get("items", []))
                    bot_count = sum(
                        slot.get("count", 0)
                        for slot in items
                        if item in slot.get("item", "")
                    )
                    if bot_count > 0:
                        holder = bot
                    total += bot_count
                details["expected"] = f">= {min_count} {item}"
                details["actual"] = f"{total} {item} (across {len(all_bots)} bots)"
                if holder:
                    details["holder"] = holder
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

    def _resolve_bots(self, world: TestWorld) -> list[str]:
        for _ in range(3):
            try:
                bots = self._api_get(world.mod_api_url, "/bots")
                bot_list = bots.get("bots", [])
                if bot_list:
                    return [
                        b["name"] if isinstance(b, dict) else b
                        for b in bot_list
                    ]
            except Exception:
                time.sleep(2)
        return []

    def run_test(self, test_def: TestDefinition) -> TestResult:
        start = time.time()
        world = None
        try:
            if test_def.description:
                print(f"[harness] {test_def.description.strip()}")
            if test_def.goal:
                print(f"[harness] Goal: {test_def.goal.strip()}")

            world = create_world(
                test_def.name, ttl=test_def.ttl,
                world_type=test_def.world_type,
                world_settings=test_def.world_settings,
            )

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

            bot_names = self._resolve_bots(world)
            if not bot_names:
                return TestResult(
                    test_name=test_def.name, passed=False,
                    duration=time.time() - start,
                    error="No bots available in test world",
                    logs=get_logs(world, "agent", 50),
                )

            default_bot = bot_names[0]
            print(f"[harness] Bots available: {', '.join(bot_names)}")
            if world.nodeport:
                print(f"[harness] Minecraft client: connect to any node IP on port {world.nodeport}")
                print(f"[harness] Dashboard: http://{test_def.name}.mc-test.local")

            step_results: list[StepResult] = []
            all_passed = True
            current_phase = ""
            total_steps = len(test_def.steps)
            phases_seen: set[str] = set()
            phases_passed: set[str] = set()
            phase_has_failure: set[str] = set()

            for i, step in enumerate(test_def.steps, 1):
                if step.phase and step.phase != current_phase:
                    current_phase = step.phase
                    phases_seen.add(current_phase)
                    print(f"\n--- Phase: {current_phase} ---")

                elapsed = time.time() - start
                target_bot = step.bot or default_bot
                print(f"[harness] Step {i}/{total_steps}: {step.instruction}")
                print(f"[harness]   bot={target_bot}, timeout={step.timeout}s, elapsed={elapsed/60:.0f}m")

                step_start = time.time()

                try:
                    self._api_post(
                        world.agent_api_url, "/api/command",
                        {"bot": target_bot, "message": step.instruction},
                    )
                except Exception as e:
                    sr = StepResult(
                        step=step.instruction, passed=False,
                        duration=time.time() - step_start,
                        details={"error": f"Failed to send instruction: {e}"},
                        phase=step.phase,
                    )
                    step_results.append(sr)
                    all_passed = False
                    if step.phase:
                        phase_has_failure.add(step.phase)
                    if test_def.halt_on_failure:
                        print("[harness] Halting on failure (halt_on_failure=true)")
                        break
                    continue

                passed = False
                details: dict[str, Any] = {}
                deadline = time.time() + step.timeout

                while time.time() < deadline:
                    time.sleep(5)
                    passed, details = self._check_success(
                        step.success, world, target_bot,
                    )
                    if passed:
                        break

                sr = StepResult(
                    step=step.instruction, passed=passed,
                    duration=time.time() - step_start,
                    details=details,
                    phase=step.phase,
                )
                step_results.append(sr)

                tag = "PASS" if passed else "FAIL"
                print(f"[harness] [{tag}] Step {i} ({sr.duration:.0f}s) {details}")

                if not passed:
                    all_passed = False
                    if step.phase:
                        phase_has_failure.add(step.phase)
                    if test_def.halt_on_failure:
                        print("[harness] Halting on failure (halt_on_failure=true)")
                        break
                else:
                    if step.phase:
                        phases_passed.add(step.phase)

            phases_fully_passed = phases_seen - phase_has_failure
            logs = get_logs(world, "agent", 100)

            return TestResult(
                test_name=test_def.name, passed=all_passed,
                duration=time.time() - start,
                step_results=step_results,
                logs=logs,
                phases_completed=len(phases_fully_passed),
                phases_total=len(phases_seen),
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
        print(f"Test: {test_def.name}")
        if test_def.description:
            desc = test_def.description.strip()
            print(f"  {desc[:120]}")
        print(f"  Steps: {len(test_def.steps)}, TTL: {test_def.ttl}s, World: {test_def.world_type}")
        print(f"{'='*60}")
        result = runner.run_test(test_def)
        results.append(result)

        status = "PASS" if result.passed else "FAIL"
        passed_steps = sum(1 for sr in result.step_results if sr.passed)
        total_steps = len(result.step_results)
        print(f"\n[{status}] {result.test_name}")
        print(f"  Duration: {result.duration:.0f}s ({result.duration/60:.1f}m)")
        print(f"  Steps: {passed_steps}/{total_steps} passed")
        if result.phases_total > 0:
            print(f"  Phases: {result.phases_completed}/{result.phases_total} fully passed")

        current_phase = ""
        for sr in result.step_results:
            if sr.phase and sr.phase != current_phase:
                current_phase = sr.phase
                print(f"  --- {current_phase} ---")
            s = "PASS" if sr.passed else "FAIL"
            step_desc = sr.step[:70] + ("..." if len(sr.step) > 70 else "")
            print(f"  [{s}] {step_desc} ({sr.duration:.1f}s)")
        if result.error:
            print(f"  ERROR: {result.error}")
    return results
