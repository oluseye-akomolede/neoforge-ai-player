"""Tests for agent/scripts/scout.js — the M2 first script (8.2).

THE POINT OF THIS FILE, after the 2026-11-13 rewrite: scout.js runs through the
runner's REAL engine, byte for byte as committed, and every assertion is made
against the SAME collector the runner uses to build a tick payload.

What it used to do, and why that was worse than useless. The old `_run` did:

    body = src.replace("\\ntick();", "\\n;return tick();")
    assert body != src, "scout.js no longer ends with a bare tick(); ..."

-- it EDITED the artefact into a shape its own assertion could read, then ran
it under a hand-rolled `new Function(...)` harness with `api.do` stubbed to a
no-op. So the test asserted that a REWRITTEN script's RETURN VALUE contained
the action, while the real runner (a) runs the source unmodified, (b) collects
actions only from api.do (agent-script-runner src/worker.js:86
`actions: state.actions ?? []`), and (c) discards a script's return value
outright (src/engine.js, contract §4.4: "§4.4's rule that the return value is
ignored holds either way").

The consequence was not a weak test, it was an inverted one: it was GREEN while
production emitted zero actions on every tick. Measured on TEST 2026-11-13
against the live runner, the committed bytes returned
{"status":"ok","actions":[]}, while a probe identical except for calling
api.do returned actions:[{directive:"STORE_ALL"}] -- and this file's suite was
passing throughout.

Two rules follow, and they are why this file looks the way it does:

1. NO SOURCE REWRITE. scout.js is read from disk and handed to the engine
   exactly as committed. If the script's contract changes, this test must go
   red, not quietly rewrite it.
2. NO api.do STUB. api.do is the only channel the runner reads, so stubbing it
   removes the thing under test. The real binding records into the real
   tick state, and the assertion reads that.

The load-bearing assertion is `test_returns_exactly_the_parity_directive`. 8.2
compares the script path's POST body against the planner path's, and that
comparison is only worth anything if the SCRIPT supplies the directive. If this
test pinned the expectation loosely (a kind, or a non-empty list), a script that
later emitted nothing would still pass while 8.2 compared two empty bodies --
the harness-writes-both-sides defect the reviewer named. So the whole action
record is pinned, not a field of it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))

# The two real modules the end-to-end chain joins. Loaded by path, like the
# rest of this suite, so the test exercises the committed bytes.
import importlib.util as _ilu


def _load_mod(name, filename):
    _spec = _ilu.spec_from_file_location(name, os.path.join(_HERE, filename))
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod


_script_tick = _load_mod("script_tick_for_e2e", "script_tick.py")
_action_binding = _load_mod("action_binding_for_e2e", "action_binding.py")
_SCRIPT = os.path.join(_HERE, "scripts", "scout.js")

# The runner's real engine. Resolved from the repo layout: this agent and the
# runner are sibling checkouts under ~/minecraft (and under the worktrees, where
# the sibling is <repo>-wt-<seat>/agent-script-runner). AGENT_SCRIPT_RUNNER
# overrides it for a checkout somewhere else. The test SKIPS loudly rather than
# silently passing when the runner is not present -- a test that cannot run must
# not look like a test that passed.
_RUNNER_ENV = "AGENT_SCRIPT_RUNNER"


def _runner_root() -> str | None:
    """Path to the agent-script-runner checkout, or None if not found."""
    candidates = []
    override = os.environ.get(_RUNNER_ENV)
    if override:
        candidates.append(override)
    # This file: <root>/<repo>/agent/test_scout_script.py
    candidates.append(str(Path(_HERE).parents[1] / "agent-script-runner"))
    # A worktree is <root>/<repo>-wt-<seat>/<repo>, so the runner is not next
    # door and not up from here: it is a SIBLING of the worktree directory --
    # one level ACROSS. Walking up alone finds it only for a plain checkout.
    # Measured 2026-11-13 before this branch existed: "Ran 9 tests in 0.002s /
    # OK (skipped=9)" -- a green that ran nothing, on the file written to
    # prevent exactly that.
    for parent in Path(_HERE).parents:
        candidates.append(str(parent / "agent-script-runner"))
        candidates.extend(str(s) for s in sorted(parent.parent.glob("*/agent-script-runner")))
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, "src", "engine.js")):
            return cand
    return None


# The driver runs INSIDE the runner checkout so `import` resolves the runner's
# own `src/engine.js` and its node_modules (quickjs), rather than reimplementing
# the sandbox. It reads the script from the path handed to it and evaluates it
# UNMODIFIED. Output is the engine's own tick state, so the actions come from
# `api.do` through `createApi` -- the same code path worker.js uses.
_DRIVER = r"""
import { loadModule, createLimitedRuntime, Sandbox } from "./src/engine.js";
import { readFileSync } from "node:fs";

const [scriptPath, snapshotJson, memoryJson] = process.argv.slice(2);
const source = readFileSync(scriptPath, "utf8");
// A sentinel, not `undefined`: "undefined" is not valid JSON, and null is a
// real (different) case the engine distinguishes from an absent snapshot.
const NO_SNAPSHOT = "__NO_SNAPSHOT__";
const snapshot = snapshotJson === NO_SNAPSHOT ? undefined : JSON.parse(snapshotJson);
// Memory is the blob this tick STARTS with. The engine's `decodeMemory`
// expects BASE64 (engine.js:1056-1062), so the driver encodes the JSON here --
// passing raw JSON silently decodes to null and recall() would return null,
// making a cooldown test pass against no memory at all.
const memory = memoryJson
  ? Buffer.from(memoryJson, "utf8").toString("base64")
  : null;

await loadModule();
const rt = await createLimitedRuntime();
// bindApi installs the real `api` (do/say/send/remember/recall/log) into the
// context, recording into the sandbox's own tick state. That is the collector
// worker.js serialises as `actions`, so nothing here imitates it.
const box = new Sandbox(rt, { tickCpuMs: 250, bindApi: true });
const result = box.evaluate(SOURCE(snapshot), { snapshot, memory });

const st = box.tickState;
process.stdout.write(JSON.stringify({
  ok: result.ok,
  error: result.ok ? null : String(result.error && (result.error.message || result.error.kind)),
  actions: st.actions.map((a) => ({ seq: a.seq, call: a.call, directive: a.directive, args: a.args })),
  logs: st.logs.map((l) => String(l.line)),
  host_calls: st.hostCalls,
  memory: st.memoryOut,
}));
"""


def _run(snapshot, script_path=None, memory=None):
    """Evaluate the COMMITTED scout.js bytes in the runner's real engine.

    Returns {"ok", "error", "actions", "logs", "host_calls"}. `actions` is the
    runner's own record shape ({seq, call, directive, args}), read from the
    sandbox's tick state -- not from the script's return value, which the
    runner ignores.
    """
    root = _runner_root()
    if root is None:
        raise unittest.SkipTest(
            f"agent-script-runner not found (set {_RUNNER_ENV}); this test must "
            "run the real engine, not a stand-in")
    # Written as a file, not `-e`: the driver is an ES module and must resolve
    # relative imports from the runner's own root.
    driver = os.path.join(root, "__scout_driver__.mjs")
    try:
        with open(driver, "w", encoding="utf-8") as fh:
            fh.write(_DRIVER.replace("SOURCE(snapshot)", "source"))
        if snapshot is None:
            snap_json = "__NO_SNAPSHOT__"
        elif isinstance(snapshot, str):
            # Only the sentinel is passed through as a bare string; everything
            # else is JSON so the driver never has to guess.
            snap_json = snapshot
        else:
            snap_json = json.dumps(snapshot)
        out = subprocess.run(
            ["node", driver, script_path or _SCRIPT, snap_json,
             json.dumps(memory) if memory is not None else ""],
            cwd=root, capture_output=True, text=True, timeout=120,
        )
    finally:
        try:
            os.remove(driver)
        except OSError:
            pass
    if out.returncode != 0:
        raise AssertionError(f"node failed: {out.stderr.strip()}")
    return json.loads(out.stdout)


# The two directive shapes the mod really returns, copied verbatim from TEST
# on 2026-11-12 (deploy/aibot-agent-test, api.get_directive("Scout")).
#
# IDLE_DIRECTIVE is what a bot standing still reports. It is an OBJECT, not
# null -- which is why `if (snapshot.task) return []` silenced the script on
# every tick of run 2. BUSY_DIRECTIVE is one captured while a WIDE_SEARCH was
# genuinely running. The discriminator is progress.phase: "idle" at rest, a
# real phase while working.
#
# These are copied from the producer's response, not constructed from what the
# script wants. A hand-written `task: null` for idle is precisely the fixture
# error that has now hidden three dead guards in this file.
IDLE_DIRECTIVE = {"state": "Standing by", "self_preservation": "ok",
                  "progress": {"phase": "idle"}}

BUSY_DIRECTIVE = {
    "state": "Wide search for minecraft:oak_log — moving to cell 1/25 [bot 1/1]",
    "self_preservation": "ok",
    "directive": {"id": 7, "type": "WIDE_SEARCH", "status": "ACTIVE",
                  "target": "minecraft:oak_log", "radius": 32, "count": 3},
    "progress": {"phase": "pathing_to_cell",
                 "recent_events": ["Wide search: target=minecraft:oak_log"]},
}


# The three shapes a TERMINATED directive reports, one per DirectiveStatus
# terminal value (DirectiveStatus.java: COMPLETED, FAILED, CANCELLED).
#
# Not hand-written. On every terminal path BotBrain swaps `activeBehavior` to
# idleBehavior while `lastProgress` keeps that behaviour's final phase, and
# :187-190 reports it for as long as `lastDirective` is set -- which is forever.
# So the payload pairs a state of "Standing by" (IdleBehavior.describeState(),
# IdleBehavior.java:24 -- NOT the literal "idle") with a non-idle phase. That
# contradiction is the bug M3-1b fixes: "the work is over" and "a plan is in
# flight" were being read from the same field.
#
# The status strings are `status.name()` from Directive.toMap() (Directive.java:63).
# The phases are what each path leaves behind: "skill:done"/"done" on success
# (SkillBehavior.java:365, LocateBehavior.java:317), "failed" on failure, and
# the phase unchanged on cancel.
COMPLETED_SKILL_DIRECTIVE = {
    "state": "Standing by",
    "self_preservation": "ok",
    "directive": {"id": 12, "type": "SKILL", "status": "COMPLETED"},
    "progress": {"phase": "skill:done"},
}

COMPLETED_DONE_DIRECTIVE = {
    "state": "Standing by",
    "self_preservation": "ok",
    "directive": {"id": 13, "type": "LOCATE", "status": "COMPLETED"},
    "progress": {"phase": "done"},
}

FAILED_DIRECTIVE = {
    "state": "Standing by",
    "self_preservation": "ok",
    "directive": {"id": 14, "type": "MINE", "status": "FAILED",
                  "failure_reason": "no blocks in range"},
    "progress": {"phase": "skill:failed"},
}

CANCELLED_DIRECTIVE = {
    "state": "Standing by",
    "self_preservation": "ok",
    "directive": {"id": 15, "type": "WIDE_SEARCH", "status": "CANCELLED"},
    "progress": {"phase": "pathing_to_cell"},
}

# Never run: no directive at all, and the phase the brain reports before any
# dispatch. This is the one shape the OLD gate handled (via phase), and it must
# keep working -- the fix adds an opening, it does not replace one.
NEVER_RUN_DIRECTIVE = {"state": "Standing by", "self_preservation": "ok",
                       "progress": {"phase": "idle"}}

# A directive carrying no progress block at all: an older mod, or a shape the
# script has not seen. The gate must hold AND must say it could not read it.
UNREADABLE_DIRECTIVE = {"state": "Standing by", "self_preservation": "ok"}

# An ARMED directive whose status the script does not recognise. Not terminal,
# not ACTIVE -- the safe answer is to hold, never to read it as idle.
UNKNOWN_STATUS_DIRECTIVE = {
    "state": "Standing by",
    "self_preservation": "ok",
    "directive": {"id": 16, "type": "MINE", "status": "PENDING"},
    "progress": {"phase": "mining"},
}


def _envelope(health=20.0, task=IDLE_DIRECTIVE, inventory=None, **extra):
    """A snapshot in the shape SnapshotCache.get actually produces.

    The flat {"health": ...} literals these tests used to pass are the shape
    scout.js WANTS; production sends {tick,server_ms,state,events,task} with
    the bot facts under `state`. Tests written against the wished-for shape are
    what let a dead guard pass three green suites, so this builds the real one
    by default. test_guards_fire_on_the_envelope_the_cache_actually_produces
    goes further and builds it through the cache itself.

    `task` defaults to IDLE_DIRECTIVE, the real idle directive, NOT None. A
    None default meant every test below exercised a state production never
    sends, and the always-truthy guard passed while silencing every run.
    """
    env = {"tick": 1, "server_ms": 1700000000000, "events": [],
           "state": {"health": health, "food": 18,
                     "position": {"x": 0.0, "y": 64.0, "z": 0.0,
                                  "dim": "minecraft:overworld"},
                     "inventory": {"inventory": []} if inventory is None else inventory,
                     "nearby": {"blocks": [], "mobs": []}},
           "task": task}
    env.update(extra)
    return env


def _directives(result):
    """The directive names the runner collected, in call order."""
    return [a["directive"] for a in result["actions"]]


# A bot that is actually carrying something, in the wrapper shape the endpoint
# really sends (HttpApiServer.java:469 -> {"inventory": api.inventory(bot)}).
# Tests that pin a CHANNEL or the directive's FORM need the bot to act, and
# since the store is now gated on having something to store, an empty
# inventory would leave them asserting a silence that has nothing to do with
# what they are testing.
CARRYING = {"inventory": [{"slot": 0, "item": "minecraft:torch", "count": 12,
                          "display_name": "Torch", "max_stack_size": 64}]}


@unittest.skipUnless(shutil.which("node"), "node is required to run scout.js")
class ScoutScriptTest(unittest.TestCase):

    def test_returns_exactly_the_parity_directive(self):
        # 8.2's subject, pinned in full: exactly one api.do, with the coordless
        # STORE_ALL and an empty args object. STORE_ALL is emitted BARE here on
        # purpose, and §3 pins that coordless form: it is what every producer in
        # this repo emits (agent.py:1622's pattern has no capture groups).
        result = _run(_envelope(20.0, inventory=CARRYING))
        self.assertTrue(result["ok"], f"engine rejected the script: {result['error']}")
        self.assertEqual(
            result["actions"],
            [{"seq": 1, "call": "do", "directive": "STORE_ALL", "args": {}}],
            f"script emitted {result['actions']!r}, logs={result['logs']!r}")

    def test_action_is_emitted_through_api_do_not_a_returned_array(self):
        # THE RUN-3 REGRESSION, pinned directly. scout.js used to
        # `return [{kind:"STORE_ALL"}]` from tick() and end with a bare
        # `tick();`. The runner ignores return values (contract §4.4) and
        # collects actions only from api.do, so the action vanished and
        # state.actions was empty on every tick of every run.
        #
        # The assertion is not "actions is non-empty" -- a script could populate
        # it any way it liked. It is that the action arrived through the `do`
        # call, which is the only channel the runner reads.
        result = _run(_envelope(20.0, inventory=CARRYING))
        self.assertTrue(result["ok"], f"engine rejected the script: {result['error']}")
        self.assertEqual(len(result["actions"]), 1,
                         f"expected exactly one action, got {result['actions']!r}")
        self.assertEqual(result["actions"][0]["call"], "do",
                         "the action must arrive through api.do; the runner "
                         "ignores a script's return value (§4.4)")
        self.assertGreaterEqual(result["host_calls"], 1,
                                "an api.do call must register as a host call")

    def test_a_returned_array_never_calls_api_do_and_yields_no_actions(self):
        # THE NEGATIVE TEST the lead asked for, and the one that would have
        # caught the original bug: a script that RETURNS the action instead of
        # calling api.do produces ZERO actions in the runner.
        #
        # It is deliberately the old scout.js shape, run through the same real
        # engine. Green here is the proof that returning is not a channel; red
        # would mean the engine started honouring return values and this test
        # file's whole premise needs revisiting.
        old_shape = (
            "function tick() { return [{ kind: 'STORE_ALL' }]; }\n"
            "tick();\n"
        )
        path = os.path.join(_HERE, "scripts", "__negative_return__.js")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(old_shape)
            # Same driver, same engine, only the source differs.
            result = _run(_envelope(20.0), script_path=path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        self.assertTrue(result["ok"], f"engine rejected the script: {result['error']}")
        self.assertEqual(
            result["actions"], [],
            "a script that RETURNS an action instead of calling api.do must "
            f"produce no actions; got {result['actions']!r}. If this is red the "
            "engine now reads return values and every assumption in this file "
            "needs re-deriving.")

    def test_no_snapshot_proposes_nothing_and_says_so(self):
        result = _run(None)
        self.assertEqual(result["actions"], [])
        self.assertTrue(any("no snapshot" in line for line in result["logs"]),
                        f"silence was unexplained: {result['logs']!r}")

    def test_low_health_holds(self):
        result = _run(_envelope(3.0))
        self.assertEqual(result["actions"], [])
        self.assertTrue(any("too low" in line for line in result["logs"]), result["logs"])

    def test_busy_bot_does_not_stack_a_second_action(self):
        # The real busy directive, captured from TEST mid-WIDE_SEARCH. The old
        # fixture was {"type": "MINE"} -- a shape the mod never returns, which
        # happened to be truthy and so "passed" the same wrong guard.
        result = _run(_envelope(20.0, BUSY_DIRECTIVE))
        self.assertEqual(result["actions"], [],
                         "script started an action under one already in flight")

    def test_real_idle_directive_does_not_silence_the_script(self):
        # THE RUN-2 REGRESSION. The mod reports an idle bot as an OBJECT
        # {"state":"Standing by","progress":{"phase":"idle"}}, never null. A
        # guard on the object's truthiness therefore read every idle bot as
        # busy and the script proposed nothing, on every tick, forever.
        #
        # This asserts the script ACTS on the exact bytes an idle bot emits.
        # It fails against `if (snapshot.task)` and passes only when the guard
        # reads progress.phase.
        result = _run(_envelope(20.0, IDLE_DIRECTIVE, inventory=CARRYING))
        self.assertEqual(_directives(result), ["STORE_ALL"],
                         "an idle bot was treated as busy; actions="
                         f"{result['actions']!r} logs={result['logs']!r}")

    def test_guards_fire_on_the_envelope_the_cache_actually_produces(self):
        # THE FIX FOR THE THIRD FIXTURE-VS-PRODUCER GAP.
        #
        # Every test above feeds scout.js a FLAT object like
        # {"health": 20, "task": null}. That is the shape the script wants, not
        # the shape it gets: production passes the envelope from
        # SnapshotCache.get, which is {"tick","server_ms","state","events",
        # "task"} with health inside `state`. So `snapshot.health` was
        # undefined, `typeof health === "number"` short-circuited, and the
        # low-health guard NEVER FIRED - a hurt bot still proposed STORE_ALL.
        # Three green suites could not see it because every fixture agreed with
        # the reader instead of with the producer.
        #
        # This builds the envelope THROUGH SnapshotCache and feeds the script
        # exactly that, so the guard is tested against bytes production emits.
        import snapshot as snap

        class _Api:
            def __init__(self, health, directive):
                self._health, self._directive = health, directive
            def status(self, bot):
                return {"health": self._health, "food": 18,
                        "position": {"x": 0.0, "y": 64.0, "z": 0.0,
                                     "dim": "minecraft:overworld"}}
            def inventory(self, bot):
                # One real entry: a bot with nothing carried has nothing to
                # store, so an empty list here would test the empty branch and
                # the healthy case below could never act.
                return {"inventory": [{"slot": 0, "item": "minecraft:torch",
                                       "count": 12, "display_name": "Torch",
                                       "max_stack_size": 64}]}
            def blocks(self, bot, radius=8): return []
            def entities(self, bot, radius=24.0): return []
            def get_directive(self, bot): return self._directive

        def envelope_json(health, directive):
            cache = snap.SnapshotCache(_Api(health, directive), ttl=60.0,
                                       clock=lambda: 1000.0)
            return cache.get("Scout")[0]

        # Healthy and idle: acts, as before.
        healthy = _run(envelope_json(20.0, None))
        self.assertEqual(_directives(healthy), ["STORE_ALL"],
                         f"real envelope broke the happy path: {healthy}")

        # HURT and idle: must hold. This is the branch that never ran.
        hurt = _run(envelope_json(3.0, None))
        self.assertEqual(
            hurt["actions"], [],
            "a bot at health 3 still proposed an action - the low-health guard "
            "is not reading the envelope production sends")
        self.assertTrue(any("too low" in line for line in hurt["logs"]),
                        f"held without saying why: {hurt['logs']!r}")

        # Task in flight: holds, and now on the real envelope rather than a
        # flat one - the task-guard fix at snapshot.py:144.
        busy = _run(envelope_json(20.0, {"type": "MINE", "status": "running"}))
        self.assertEqual(busy["actions"], [],
                         "script started an action under one already in flight")

    def test_zero_actions_paths_are_distinguishable_from_a_silent_script(self):
        # A script that returns [] because it CHOSE to is different from one
        # that failed. The three empty-return paths above each log a reason or
        # are a deliberate no-op (busy); the busy path logs nothing because the
        # agent already knows why. This asserts the two self-explaining paths
        # do explain, so 8.2 can tell "held" from "broke".
        for literal, token in ((None, "no snapshot"),
                               (_envelope(3.0), "too low")):
            logs = _run(literal)["logs"]
            self.assertTrue(any(token in line for line in logs),
                            f"{literal} returned [] without explaining: {logs!r}")


class ActsOnlyWhenThereIsSomethingToDoTest(unittest.TestCase):
    """M3-1: a store is proposed only when there is something to store.

    Measured on test 2026-11-18: 77 STORE_ALL proposals in about three minutes,
    every one of them from an idle bot with an empty inventory. Every guard in
    scout.js was passing correctly - the snapshot was there, the health was
    fine, the task was provably idle - so no assertion below could have caught
    it from the existing suite. The missing guard is the subject here.

    THE FIXTURE SHAPE IS THE POINT OF THIS CLASS. The producer's body is
    HttpApiServer.java:469 `Map.of("inventory", bot.getCachedInventory())`, so
    `snapshot.state.inventory` is `{"inventory": [...]}` - an OBJECT. A guard
    written against a bare array (`state.inventory.length > 0`) reads undefined,
    compares false, and silently never stores anything, which is the direction
    that looks like a fix in review and is not one. `test_guard_reads_the_wrapper`
    below is the one that fails against that mistake; the others would pass
    because an empty bare array and an empty wrapper both mean "nothing".
    """

    # One real entry, in the shape BotPlayer.serializeItemStack builds
    # (BotPlayer.java:994-998): slot, item, count, display_name, max_stack_size.
    _TORCH = {"slot": 0, "item": "minecraft:torch", "count": 12,
              "display_name": "Torch", "max_stack_size": 64}

    def test_empty_inventory_proposes_nothing(self):
        result = _run(_envelope(20.0, inventory={"inventory": []}))
        self.assertTrue(result["ok"], f"engine rejected: {result['error']}")
        self.assertEqual(_directives(result), [],
                         f"empty inventory still proposed: {result['actions']}")
        self.assertTrue(any("empty" in line for line in result["logs"]),
                        f"held without saying why: {result['logs']!r}")

    def test_carried_items_and_idle_propose_one_store(self):
        result = _run(_envelope(20.0, inventory={"inventory": [self._TORCH]}))
        self.assertTrue(result["ok"], f"engine rejected: {result['error']}")
        self.assertEqual(_directives(result), ["STORE_ALL"])

    def test_guard_reads_the_wrapper_not_a_bare_array(self):
        """The wrapper is a dict, so `.length` is undefined on it.

        A bare-array guard is the mistake this pins: `state.inventory.length`
        is absent on an object, so `> 0` is false and the script stores NOTHING
        while every other test in this class still passes. Both directions are
        asserted so a script that ignores inventory entirely cannot pass either.
        """
        full = _run(_envelope(20.0, inventory={"inventory": [self._TORCH]}))
        empty = _run(_envelope(20.0, inventory={"inventory": []}))
        self.assertEqual(_directives(full), ["STORE_ALL"],
                         "a non-empty wrapper did not propose a store: the guard "
                         "is reading the wrapper as if it were the list")
        self.assertEqual(_directives(empty), [],
                         "an empty wrapper proposed a store")

    def test_cooldown_holds_a_repeat_store(self):
        """One store, then nothing until the cooldown has elapsed.

        `api.recall()` returns the blob the tick STARTED with (contract-v1.md
        :282-285), and a `remember` in the same tick does not change it. So the
        remembered state is supplied here as the tick's input, exactly as the
        game would: tick 5 stored at tick 5, and tick 6 is one tick later.
        """
        first = _run(_envelope(20.0, tick=5,
                               inventory={"inventory": [self._TORCH]}))
        self.assertEqual(_directives(first), ["STORE_ALL"])

        soon = _run(_envelope(20.0, tick=6,
                              inventory={"inventory": [self._TORCH]}),
                    memory={"lastStoreAllTick": 5})
        self.assertEqual(_directives(soon), [],
                         "stored again one tick later, so a failing store would "
                         "loop every tick")
        self.assertTrue(any("cooling down" in line.lower() for line in soon["logs"]),
                        f"held without saying why: {soon['logs']!r}")

    def test_cooldown_expires(self):
        """Past the cooldown the bot stores again - otherwise it stores once ever."""
        later = _run(_envelope(20.0, tick=500,
                               inventory={"inventory": [self._TORCH]}),
                     memory={"lastStoreAllTick": 5})
        self.assertEqual(_directives(later), ["STORE_ALL"],
                         "cooldown never expired; the bot would store once and stop")

    def test_cooldown_is_measured_from_the_remembered_tick(self):
        """The remembered tick is what the cooldown is compared against.

        The driver supplies `memory` as the blob the tick started with; this
        asserts the script writes that blob rather than merely holding a local
        counter that dies with the disposable sandbox.
        """
        result = _run(_envelope(20.0, tick=7,
                                inventory={"inventory": [self._TORCH]}))
        blob = result.get("memory")
        self.assertIsNotNone(blob, "stored without remembering the tick")
        # memoryOut is the runner's JSON string, not a live object.
        self.assertEqual(json.loads(blob).get("lastStoreAllTick"), 7)


class HeldTickIsObservableTest(unittest.TestCase):
    """M3-1b cause B: a held tick leaves evidence.

    On test 2026-11-19 Scout held 16 cobblestone and did not store for at least
    seven minutes while the log carried ZERO script dispatch lines. A held bot,
    a bot the caller never invoked, and an unreachable script all looked
    identical from outside, so no cause could be named from the evidence.

    These tests fail on 69fc324: the gate returned silently, so `logs` carried
    no line at all. They assert the log line, not the decision - the gate's
    hold is correct and this change deliberately does not alter it.
    """

    def test_busy_tick_logs_the_phase_it_saw(self):
        """A recognised non-idle phase is named in the log."""
        result = _run(_envelope(20.0, BUSY_DIRECTIVE, inventory=CARRYING))
        self.assertEqual([], result["actions"],
                         "a busy bot must not act: %r" % (result["actions"],))
        joined = " ".join(result["logs"])
        self.assertIn("pathing_to_cell", joined,
                      "the log must name the phase it held on; got %r"
                      % (result["logs"],))

    def test_completed_plan_opens_the_gate(self):
        """M3-1b: a FINISHED plan must not hold the bot forever.

        On SUCCESS BotBrain swaps in idleBehavior but `lastProgress` keeps the
        behaviour's final phase, so the payload reads `state: "Standing by"`
        beside `progress.phase: "skill:done"` on every tick, forever. Keying
        the gate on the phase held the bot permanently after its first plan;
        the question is whether a directive is in FLIGHT, and the status
        answers it. A COMPLETED directive is not in flight.
        """
        result = _run(_envelope(20.0, COMPLETED_SKILL_DIRECTIVE,
                                inventory=CARRYING))
        self.assertEqual(["STORE_ALL"], _directives(result),
                         "a completed plan must not hold the bot: logs=%r"
                         % (result["logs"],))
        joined = " ".join(result["logs"])
        self.assertNotIn("holding", joined,
                         "nothing is being held; got %r" % (result["logs"],))

    def test_every_terminal_status_opens_the_gate(self):
        """COMPLETED, FAILED and CANCELLED all mean 'not in flight'.

        The reviewer's correction: `lastDirective` is set on all three terminal
        paths (BotBrain.java:93 SUCCESS, :106 FAILED, :118 CANCELLED), not only
        on success, so a FAILED directive strands the bot exactly the same way.
        One fixture per status, each in the shape the producer emits.
        """
        for name, fixture, phase in (
                ("COMPLETED/skill:done", COMPLETED_SKILL_DIRECTIVE, "skill:done"),
                ("COMPLETED/done", COMPLETED_DONE_DIRECTIVE, "done"),
                ("FAILED", FAILED_DIRECTIVE, "skill:failed"),
                ("CANCELLED", CANCELLED_DIRECTIVE, "pathing_to_cell")):
            with self.subTest(status=name):
                result = _run(_envelope(20.0, fixture, inventory=CARRYING))
                self.assertEqual(
                    ["STORE_ALL"], _directives(result),
                    "%s is terminal and must not hold; logs=%r"
                    % (name, result["logs"]))
                # The stale phase must not drive the decision any more.
                self.assertNotIn("holding", " ".join(result["logs"]),
                                 "%s held on stale phase %r: %r"
                                 % (name, phase, result["logs"]))

    def test_never_run_bot_still_opens_the_gate(self):
        """The fix ADDS an opening; it must not lose the one that worked.

        A bot that has never been dispatched carries no `directive` key at all
        and reports `progress.phase: "idle"`. That was the only shape the old
        gate let through, and it must keep letting through.
        """
        result = _run(_envelope(20.0, NEVER_RUN_DIRECTIVE, inventory=CARRYING))
        self.assertEqual(["STORE_ALL"], _directives(result),
                         "a never-run bot must act: logs=%r"
                         % (result["logs"],))

    def test_active_directive_still_holds(self):
        """ACTIVE is the one in-flight status - the gate must keep holding."""
        result = _run(_envelope(20.0, BUSY_DIRECTIVE, inventory=CARRYING))
        self.assertEqual([], result["actions"],
                         "an ACTIVE directive must hold: %r"
                         % (result["actions"],))
        self.assertIn("ACTIVE", " ".join(result["logs"]),
                      "the hold must name the status it held on; got %r"
                      % (result["logs"],))

    def test_unknown_status_holds_rather_than_reading_as_idle(self):
        """A status we do not recognise is not terminal: hold, do not guess.

        Same asymmetry as an unreadable directive. If a future enum value were
        read as terminal, the script would start a second job underneath a
        live one - the exact failure this gate exists to prevent.
        """
        result = _run(_envelope(20.0, UNKNOWN_STATUS_DIRECTIVE, inventory=CARRYING))
        self.assertEqual([], result["actions"],
                         "an unknown status must hold: %r" % (result["actions"],))
        self.assertIn("PENDING", " ".join(result["logs"]),
                      "the hold should name the unrecognised status; got %r"
                      % (result["logs"],))

    def test_the_state_field_is_not_the_gate(self):
        """`state` never reads "idle" in production - it must not be tested.

        IdleBehavior.describeState() returns "Standing by" (IdleBehavior.java:24)
        and `activeBehavior` is never null (BotBrain.java:29 and every terminal
        path restore idleBehavior), so the literal "idle" at BotBrain.java:180
        is unreachable. A gate written as `state === "idle"` would never fire -
        the same dead-guard class as the flat-shape health guard. Pin it: a
        terminal fixture whose state is "Standing by" still opens the gate, and
        no test may depend on a state of "idle".
        """
        self.assertNotEqual("idle", COMPLETED_SKILL_DIRECTIVE["state"])
        self.assertNotEqual("idle", NEVER_RUN_DIRECTIVE["state"])
        result = _run(_envelope(20.0, COMPLETED_SKILL_DIRECTIVE,
                                inventory=CARRYING))
        self.assertEqual(["STORE_ALL"], _directives(result))

    def test_unreadable_directive_is_distinguished_from_a_known_phase(self):
        """No progress block logs a DISTINCT line, not a blank or a wrong phase.

        The gate holds on an unreadable directive on purpose. It must not look
        like a recognised phase in the log, or a reader cannot tell "held on
        pathing_to_cell" from "held on a shape we cannot read".
        """
        result = _run(_envelope(20.0, UNREADABLE_DIRECTIVE, inventory=CARRYING))
        self.assertEqual([], result["actions"])
        joined = " ".join(result["logs"])
        self.assertIn("no progress phase", joined,
                      "an unreadable directive needs its own line; got %r"
                      % (result["logs"],))
        self.assertNotIn("pathing_to_cell", joined)

    def test_idle_tick_logs_no_hold(self):
        """The guard must not fire on an idle bot - no spurious hold line."""
        result = _run(_envelope(20.0, IDLE_DIRECTIVE, inventory=CARRYING))
        joined = " ".join(result["logs"])
        self.assertNotIn("holding", joined,
                         "an idle bot is not held; got %r" % (result["logs"],))


class EndToEndBindingTest(unittest.TestCase):
    """The whole chain, with no hand-written fixture anywhere in it.

    scout.js runs in the runner's real engine; what that engine collected is
    translated by `script_tick.translate_runner_actions`; the translated record
    is bound by the real `action_binding.bind_actions`; and the result must be
    a dispatchable STORE_ALL. Each of the three earlier rounds broke a
    different join in this chain while its own tests stayed green, because the
    tests substituted a fixture at the join. This one substitutes nothing.
    """

    def _chain(self):
        result = _run(_envelope(20.0, inventory=CARRYING))
        self.assertTrue(result["ok"], f"engine rejected the script: {result['error']}")
        pairs, refusals = _script_tick.translate_runner_actions(result["actions"])
        self.assertEqual(refusals, [], f"translation refused {refusals!r}")
        bound, bind_refusals = _action_binding.bind_actions([b for b, _ in pairs])
        return bound, bind_refusals, pairs, result

    def test_the_engines_own_record_binds_as_store_all(self):
        bound, bind_refusals, _pairs, result = self._chain()
        self.assertEqual(bind_refusals, [],
                         f"binder refused the runner's record {result['actions']!r}")
        self.assertEqual(bound, [{"kind": "STORE_ALL"}],
                         f"bound {bound!r} from actions {result['actions']!r}")

    def test_the_binding_uses_the_directive_the_engine_emitted(self):
        # Not a constant: the expectation is read out of what the engine
        # actually collected, so this stays honest if scout.js changes.
        _bound, _ref, pairs, result = self._chain()
        self.assertEqual(pairs[0][0]["kind"], result["actions"][0]["directive"])
        self.assertEqual(pairs[0][1], result["actions"][0]["seq"])


class NoSilentSkipTest(unittest.TestCase):
    """A skip in this file must never read as a pass.

    Every test above that cannot find the runner raises SkipTest, and unittest
    reports a module whose tests all skipped as `OK (skipped=N)`. So an
    environment missing the runner -- a fresh clone, a CI box, a worktree whose
    sibling path is wrong -- printed a green line while asserting nothing. That
    is the same shape as the defect this whole file exists to catch: a check
    that cannot distinguish "ran and passed" from "never ran".

    Measured 2026-11-13, before the path fix: "Ran 9 tests in 0.002s / OK
    (skipped=9)". The message was honest and loud and still produced OK.

    This asserts the file actually ran its engine-backed tests. It is
    deliberately a hard failure, not a skip: if the runner is absent, the
    trustworthy outcome is RED, because nothing here has been verified.
    """

    def test_the_engine_backed_tests_actually_ran(self):
        root = _runner_root()
        self.assertIsNotNone(
            root,
            "agent-script-runner not found, so every test in this file "
            "SKIPPED while the suite printed OK without verifying anything. "
            "Set AGENT_SCRIPT_RUNNER to the runner checkout. Red is the "
            "correct outcome: an unverified green is the bug.")


class _SkipRecorder(unittest.TextTestResult):
    """Turn any skip in this module into a failure.

    NoSilentSkipTest above only catches the ONE cause it knows about: no runner
    on disk. Any other SkipTest -- a missing fixture, an unsupported Node, a
    future guard -- leaves _runner_root() returning a path, that test green, and
    the suite printing `OK (skipped=N)` again. That is the same hole one level
    in, so this keys on the SKIP ITSELF rather than on one reason for it.
    """

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        exc = AssertionError(
            f"test skipped instead of running: {reason}. "
            "A skip is not evidence; red is the correct outcome.")
        self.addFailure(test, (AssertionError, exc, exc.__traceback__))


class _SkipRecorderRunner(unittest.TextTestRunner):
    resultclass = _SkipRecorder


class _SkipIsFailure:
    """Wrap one test case so a skip inside it is recorded as a failure.

    Needed because the RESULT CLASS comes from the runner, and discovery builds
    its own: a module cannot swap it. `load_tests` is the hook discovery does
    honour, and it hands back a suite, so the interception has to happen per
    test case instead of per result.

    Everything is delegated to the real test case except `__call__`, which hands
    the test a thin result proxy that rewrites addSkip and forwards the rest.
    """

    def __init__(self, test):
        self._test = test

    def __call__(self, result):
        outer = result

        class _Proxy:
            def addSkip(self, test, reason):
                exc = AssertionError(
                    f"test skipped instead of running: {reason}. "
                    "A skip is not evidence; red is the correct outcome.")
                outer.addFailure(test, (AssertionError, exc, exc.__traceback__))

            def __getattr__(self, name):
                return getattr(outer, name)

        self._test(_Proxy())

    def __getattr__(self, name):
        return getattr(self._test, name)


def _wrap(case):
    """Return `case` wrapped once, leaving an existing wrapper alone.

    Must be idempotent. loadTestsFromModule turns ANY exception raised out of
    load_tests into a _FailedTest ERROR, so a double wrap that raised would
    surface as `errors=1` -- indistinguishable from the known dashboard import
    that is routinely waved through. A guard that fails as an ignorable error
    is a weak guard.
    """
    return case if isinstance(case, _SkipIsFailure) else _SkipIsFailure(case)


def load_tests(loader, tests, pattern):
    """Convert every test in this module into a skip-is-failure wrapper.

    Discovery calls this; without it the recorder above only applies to a direct
    `python3 test_scout_script.py` run, which is NOT how the suite is invoked.
    Measured 2026-11-13: a skip under discovery printed `OK (skipped=1)` rc=0
    with the guard green, so the general case was still open one level in.

    The input is a suite of suites in some paths and a flat suite of cases in
    others -- loadTestsFromModule returns the flat shape -- so classify each
    member by whether it iterates, and never rewrap what is already wrapped.
    """
    suite = unittest.TestSuite()
    for member in tests:
        try:
            cases = list(member)
        except TypeError:  # already a single (wrapped) case
            suite.addTest(_wrap(member))
        else:
            for case in cases:
                suite.addTest(_wrap(case))
    return suite


if __name__ == "__main__":
    result = _SkipRecorderRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
