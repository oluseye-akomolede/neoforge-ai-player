"""L2 orchestration for spec-driven planning.

The single public entrypoint is `execute_task(bot_name, model, task, dispatch_fn,
world_state_fn)`. It runs Phase 1 (plan) then loops Phase 2 (exec) per subtask
until the plan completes, fails, or is paused (returns).

This module is intentionally decoupled from agent.py — agent.py decides WHEN
to call execute_task and provides:
  - dispatch_fn(directive_dict) → result_text (executes a directive via L1)
  - world_state_fn() → world_state_summary string

This keeps the orchestration pure: no global state, no threads, no api module
dependencies.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

import requests

import api
import fast_planner
import l3_planner
import plan_memory
import plan_store
from criteria_eval import evaluate as evaluate_criteria
from plan_schema import Plan, PlanValidationError, Subtask

# Optional L2 translation layer (spec: l2-mcp-translation-layer). When set,
# directive normalization is delegated to the shared l2-mcp service; any
# failure falls back to the in-process copy below. Fail-open by design.
_L2_MCP_URL = os.getenv("L2_MCP_URL", "").rstrip("/")

log = logging.getLogger("aibot.orchestrator")

MAX_ATTEMPTS = 3
MAX_REPLANS_PER_SUBTASK = 2

DispatchFn = Callable[[dict[str, Any]], str]
WorldStateFn = Callable[[], str]
OnPlanCreated = Callable[[Plan], None]
OnSubtaskStart = Callable[[Plan, Subtask], None]
OnSubtaskDone = Callable[[Plan, Subtask, bool], None]
OnFinalized = Callable[[Plan], None]


def execute_task(
    bot_name: str,
    model: str,
    task: str,
    dispatch_fn: DispatchFn,
    world_state_fn: WorldStateFn | None = None,
    on_plan_created: OnPlanCreated | None = None,
    on_subtask_start: OnSubtaskStart | None = None,
    on_subtask_done: OnSubtaskDone | None = None,
    on_finalized: OnFinalized | None = None,
) -> Plan:
    """
    Run a full task end-to-end: plan → exec subtasks → return Plan.

    Returns the final Plan with status set to complete or failed. The plan
    file is also archived on disk.

    The four optional callbacks let the caller surface progress to chat,
    dashboard, or anywhere else without coupling the orchestrator to UI.
    """
    world_state_fn = world_state_fn or (lambda: "")
    noop = lambda *_a, **_kw: None
    on_plan_created = on_plan_created or noop
    on_subtask_start = on_subtask_start or noop
    on_subtask_done = on_subtask_done or noop
    on_finalized = on_finalized or noop

    # Fetch the live dimension list so L3 prompts use exact registered ids.
    # Cached for the rest of this task — dims rarely change mid-task.
    dim_list = _safe_get_dimensions()

    # Phase 0: deterministic fast path. Recognized command shapes ("mine 16
    # iron ore", "goto x y z", "teleport to the nether") skip L3 planning
    # entirely — the Plan arrives with pre-baked directives on subtask 1.
    plan = fast_planner.try_plan(bot_name, task)
    if plan is not None:
        log.info("[%s] fast-path plan (0 LLM calls): %s",
                 bot_name, plan.subtasks[0].description)
    if plan is None:
        # Phase 0.5: plan-template memory — replay a proven plan for a
        # near-identical past task (exact normalized match, count substituted).
        plan = plan_memory.lookup(bot_name, task)
        if plan is not None:
            log.info("[%s] plan-memory reuse (0 LLM planning calls)", bot_name)
    if plan is None:
        # Phase 1: L3 plan — with one retry if criteria geometry is provably
        # impossible (finding D1: PLAN-time criteria pointed below the world
        # floor / into unbuilt space and pinned execution to unpassable checks).
        try:
            plan = l3_planner.call_plan(model, bot_name, task, world_state_fn(), dimensions=dim_list)
            violations = _validate_criteria_geometry(plan)
            if violations:
                log.info("[%s] plan criteria geometry invalid, re-planning once: %s",
                         bot_name, "; ".join(violations)[:200])
                feedback = (world_state_fn() + "\n\nPREVIOUS PLAN REJECTED — invalid criteria "
                            "coordinates: " + "; ".join(violations) +
                            ". Criteria block coordinates MUST be inside the world and "
                            "within the volume your subtasks will actually build.")
                retry = l3_planner.call_plan(model, bot_name, task, feedback, dimensions=dim_list)
                retry_violations = _validate_criteria_geometry(retry)
                if not retry_violations:
                    plan = retry
                elif len(retry_violations) < len(violations):
                    log.info("[%s] retry plan still has %d geometry issue(s) — using it anyway",
                             bot_name, len(retry_violations))
                    plan = retry
        except PlanValidationError as e:
            log.warning("[%s] planning failed: %s", bot_name, e)
            # Synthetic failure plan so the caller has something to log
            import datetime
            plan = Plan(
                task=task, bot=bot_name,
                created_at=datetime.datetime.utcnow().isoformat(),
                status="failed",
                subtasks=[],
                current_subtask_id=0,
            )
            plan_store.write(plan)
            plan_store.archive(plan)
            on_finalized(plan)
            return plan

    # Baseline combat stats so "killed N enemies" criteria can be checked as
    # a delta instead of a lifetime total (war-test finding #1).
    try:
        st = api.status(bot_name)
        if isinstance(st, dict) and isinstance(st.get("mob_kills"), int) and st["mob_kills"] >= 0:
            plan.meta["kills_at_start"] = st["mob_kills"]
    except Exception as e:
        log.debug("[%s] kills baseline unavailable: %s", bot_name, e)

    plan_store.write(plan)
    log.info("[%s] plan written with %d subtasks", bot_name, len(plan.subtasks))
    try:
        on_plan_created(plan)
    except Exception:
        log.exception("[%s] on_plan_created hook raised", bot_name)

    # Phase 2: drive subtasks
    last_subtask_id = -1
    while plan.status == "executing":
        subtask = plan.current_subtask()
        if subtask is None or plan.all_complete():
            plan.status = "complete"
            break
        # Fire "subtask started" hook on transitions only
        if subtask.id != last_subtask_id:
            try:
                on_subtask_start(plan, subtask)
            except Exception:
                log.exception("[%s] on_subtask_start hook raised", bot_name)
            last_subtask_id = subtask.id
        prev_status = subtask.status
        if not _step(plan, subtask, model, dispatch_fn, world_state_fn, dim_list):
            # _step returns False when the plan needs to abort
            break
        # Fire "subtask done" hook when this subtask reached terminal state
        if subtask.status in ("complete", "failed") and prev_status not in ("complete", "failed"):
            try:
                on_subtask_done(plan, subtask, subtask.status == "complete")
            except Exception:
                log.exception("[%s] on_subtask_done hook raised", bot_name)

    plan_store.write(plan)
    plan_store.archive(plan)
    if plan.status == "complete":
        try:
            plan_memory.record(plan)
        except Exception:
            log.exception("[%s] plan-memory record failed (non-fatal)", bot_name)
    log.info("[%s] plan finalized: %s", bot_name, plan.status)
    try:
        on_finalized(plan)
    except Exception:
        log.exception("[%s] on_finalized hook raised", bot_name)
    return plan


def _safe_get_dimensions() -> list[str]:
    """Best-effort fetch of registered dimension ids from the mod API.
    Falls back to the default trio if the API isn't reachable."""
    try:
        resp = api.dimensions()
        dims = resp.get("dimensions") or []
        # Normalize: accept either list of strings or list of {id, ...} dicts
        cleaned: list[str] = []
        for d in dims:
            if isinstance(d, str):
                cleaned.append(d)
            elif isinstance(d, dict):
                v = d.get("id") or d.get("name")
                if v:
                    cleaned.append(v)
        if cleaned:
            return cleaned
    except Exception as e:
        log.debug("dimension fetch failed: %s", e)
    return list(l3_planner._DEFAULT_DIMENSIONS)


def _step(plan: Plan, subtask: Subtask, model: str,
          dispatch_fn: DispatchFn, world_state_fn: WorldStateFn,
          dim_list: list[str] | None = None) -> bool:
    """Drive one subtask through one attempt. Returns False if the plan must abort."""
    # Fast path: subtask arrived with pre-baked directives (fast_planner) and
    # this is the first attempt — skip the L3 exec call entirely. Retries
    # (attempts > 0) fall through to L3 so failures get intelligent handling.
    if subtask.directives and subtask.attempts == 0 and not subtask.error:
        directives = list(subtask.directives)
        log.info("[%s] subtask %d dispatching pre-baked directives (0 LLM calls)",
                 plan.bot, subtask.id)
    else:
        # Phase 2 exec
        try:
            directives = l3_planner.call_exec(
                model=model, plan=plan, subtask=subtask,
                world_state_summary=world_state_fn(),
                previous_error=subtask.error,
                dimensions=dim_list,
            )
        except Exception as e:
            log.warning("[%s] subtask %d exec failed: %s", plan.bot, subtask.id, e)
            subtask.attempts += 1
            subtask.error = f"exec_call_failed: {e}"
            plan_store.write(plan)
            if subtask.attempts >= MAX_ATTEMPTS:
                if not _replan(plan, subtask, model):
                    plan.status = "failed"
                    return False
            return True

    # Validate / repair directives BEFORE dispatch (TELEPORT especially).
    directives = [_repair_directive(d, plan.bot, dim_list) for d in directives]

    # Ground block-at criteria in the actual BUILD orders (finding D1):
    # deterministic derivation, not an LLM rewrite, so the anti-laundering
    # guarantee is untouched.
    derived = _derive_build_criteria(subtask, directives)
    if derived and derived != subtask.criteria:
        log.info("[%s] criteria grounded from BUILD directives: %r -> %r",
                 plan.bot, subtask.criteria, derived)
        subtask.criteria = derived

    subtask.status = "executing"
    subtask.directives = list(directives)
    plan_store.write(plan)

    # Dispatch each directive via L1
    last_result = ""
    for d in directives:
        try:
            last_result = dispatch_fn(d)
        except Exception as e:
            last_result = f"DISPATCH_ERROR: {e}"
            log.warning("[%s] dispatch failed for %s: %s", plan.bot, d.get("kind"), e)

    # Evaluate criteria
    satisfied, strategy, reason = evaluate_criteria(
        bot_name=plan.bot,
        subtask=subtask,
        last_result_text=last_result,
        model=model,
        plan=plan,
    )
    log.info("[%s] subtask %d criteria: %s (%s) — %s",
             plan.bot, subtask.id, satisfied, strategy, reason)

    if satisfied:
        subtask.status = "complete"
        subtask.error = None
        plan.advance()
        plan_store.write(plan)
        return True

    # Failed this attempt
    subtask.status = "failed"
    subtask.attempts += 1
    subtask.error = reason
    plan_store.write(plan)
    if subtask.attempts < MAX_ATTEMPTS:
        # retry
        subtask.status = "pending"
        plan_store.write(plan)
        return True

    return _replan(plan, subtask, model)


# Loose aliases the LLM might emit that map to canonical dim ids.
_DIM_ALIASES = {
    "nether": "minecraft:the_nether",
    "the nether": "minecraft:the_nether",
    "the_nether": "minecraft:the_nether",
    "end": "minecraft:the_end",
    "the end": "minecraft:the_end",
    "the_end": "minecraft:the_end",
    "overworld": "minecraft:overworld",
    "minecraft:nether": "minecraft:the_nether",
    "minecraft:end": "minecraft:the_end",
}


# Renamed/wrong mob ids the LLM emits from stale training data.
from criteria_eval import _BLOCK_PATTERN, _CLAUSE_SPLIT  # shared criterion grammar


def _probe_block(bot_name: str, x: int, y: int, z: int) -> str | None:
    """Block id at (x,y,z), or None if unavailable (fail-open)."""
    try:
        got = api.block_at(bot_name, x, y, z)
        return got.get("block") if isinstance(got, dict) else None
    except Exception:
        return None


def _validate_criteria_geometry(plan: Plan) -> list[str]:
    """Find block-at criteria that target provably impossible coordinates —
    positions outside the generated world (void_air). Returns violations."""
    out: list[str] = []
    for st in plan.subtasks:
        for clause in _CLAUSE_SPLIT.split(st.criteria or ""):
            m = _BLOCK_PATTERN.search(clause)
            if not m:
                continue
            bx, by, bz = int(m.group(1)), int(m.group(2)), int(m.group(3))
            block = _probe_block(plan.bot, bx, by, bz)
            if block == "minecraft:void_air":
                out.append(f"subtask {st.id} targets ({bx},{by},{bz}) which is outside the world")
    return out


def _criterion_impossible(bot_name: str, criteria: str) -> str | None:
    """Reason string if any block-at clause targets a void position, else None."""
    for clause in _CLAUSE_SPLIT.split(criteria or ""):
        m = _BLOCK_PATTERN.search(clause)
        if m:
            bx, by, bz = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if _probe_block(bot_name, bx, by, bz) == "minecraft:void_air":
                return f"({bx},{by},{bz}) is outside the world"
    return None


def _derive_build_criteria(subtask: Subtask, directives: list[dict]) -> str | None:
    """Ground a block-at criterion in the ACTUAL build orders (finding D1):
    PLAN-time criteria imagine coordinates; the emitted BUILD directives are
    the truth about where material will be placed. Every blueprint places its
    origin block, so 'block at (origin) is (material)' is exact."""
    if not _BLOCK_PATTERN.search(subtask.criteria or ""):
        return None
    clauses = []
    for d in directives:
        if str(d.get("kind", "")).upper() != "BUILD":
            continue
        x, y, z = int(d.get("x", 0) or 0), int(d.get("y", 0) or 0), int(d.get("z", 0) or 0)
        if x == 0 and y == 0 and z == 0:
            continue  # build-at-bot: origin unknown at dispatch time
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        material = str(extra.get("material", "minecraft:cobblestone"))
        if ":" not in material:
            material = "minecraft:" + material
        clauses.append(f"block at ({x},{y},{z}) is {material}")
    return " AND ".join(clauses) if clauses else None


# L3-invented BUILD shapes → the mod's real blueprints
_BUILD_SHAPE_ALIASES = {
    "pillar": "tower",
    "watchtower": "tower",
    "gate": "wall",
    "door": "wall",
    "cube": "shelter",
    "keep": "shelter",
    "house": "shelter",
    "fortress": "shelter",
}

_MOB_SYNONYMS = {
    "minecraft:pig_zombie": "minecraft:zombified_piglin",
    "minecraft:zombie_pigman": "minecraft:zombified_piglin",
    "pig_zombie": "minecraft:zombified_piglin",
    "zombie_pigman": "minecraft:zombified_piglin",
    "minecraft:wither_boss": "minecraft:wither",
    "minecraft:snowman": "minecraft:snow_golem",
    "minecraft:villager_golem": "minecraft:iron_golem",
}


def _repair_directive(d: dict[str, Any], bot_name: str, dim_list: list[str] | None) -> dict[str, Any]:
    """Patch common L3 directive mistakes before dispatch. Idempotent.

    Delegates to l2-mcp when L2_MCP_URL is set (authoritative vocabulary
    tables live there); the local logic below is the fail-open bypass."""
    if not isinstance(d, dict):
        return d

    if _L2_MCP_URL:
        try:
            r = requests.post(
                f"{_L2_MCP_URL}/render/normalize_directive",
                json={"directive": d, "dimensions": dim_list},
                timeout=1.5,
            )
            r.raise_for_status()
            rendered = r.json().get("rendered", {})
            nd = rendered.get("directive")
            if isinstance(nd, dict) and nd.get("kind"):
                flags = rendered.get("flags") or []
                if flags:
                    log.info("[%s] l2-mcp flags on %s: %s", bot_name, nd.get("kind"), flags)
                return nd
        except Exception as e:
            log.debug("l2-mcp normalize bypass (%s)", e)
    kind = str(d.get("kind", "")).upper()
    d["kind"] = kind
    if kind == "EQUIP":
        d["kind"] = "EQUIP_ALL"

    if kind == "COMBAT":
        tgt = str(d.get("target", "")).strip().lower()
        if tgt in _MOB_SYNONYMS:
            log.info("[%s] mob synonym: %s -> %s", bot_name, tgt, _MOB_SYNONYMS[tgt])
            d["target"] = _MOB_SYNONYMS[tgt]

    if kind == "BUILD":
        # The mod reads the blueprint from `target`; L3 tends to put it in
        # extra.shape (finding B1). Move it over and map invented shapes.
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        if not d.get("target") and extra.get("shape"):
            d["target"] = str(extra["shape"]).lower()
        if d.get("target"):
            d["target"] = _BUILD_SHAPE_ALIASES.get(
                str(d["target"]).lower(), str(d["target"]).lower())

    if kind == "TELEPORT":
        extra = d.get("extra")
        if not isinstance(extra, dict):
            extra = {}
            d["extra"] = extra
        # Coerce dimension to a known id
        dim = extra.get("dimension") or d.get("dimension")
        if dim:
            key = str(dim).strip().lower()
            canonical = _DIM_ALIASES.get(key, dim)
            if dim_list and canonical not in dim_list:
                # Try matching by suffix (e.g. LLM wrote "the_nether" we have "minecraft:the_nether")
                suffix = canonical.rsplit(":", 1)[-1]
                match = next((d2 for d2 in dim_list if d2.endswith(":" + suffix) or d2 == suffix), None)
                if match:
                    canonical = match
            extra["dimension"] = canonical
        # Reject 0,0,0 with no dimension change — coerce y to surface height
        x = int(d.get("x", 0) or 0)
        y = int(d.get("y", 0) or 0)
        z = int(d.get("z", 0) or 0)
        if x == 0 and z == 0 and y == 0:
            # Safer default: spawn-ish coords above surface
            d["y"] = 70
            log.info("[%s] TELEPORT had 0,0,0 — coerced y to 70", bot_name)
    return d


def _replan(plan: Plan, failed_subtask: Subtask, model: str) -> bool:
    """Try to replan a failed subtask. Returns False if the plan must abort."""
    if failed_subtask.replans >= MAX_REPLANS_PER_SUBTASK:
        log.warning("[%s] subtask %d exhausted replans (%d), failing plan",
                    plan.bot, failed_subtask.id, failed_subtask.replans)
        plan.status = "failed"
        return False
    try:
        new_subtask = l3_planner.call_replan(model, plan, failed_subtask)
    except PlanValidationError as e:
        log.warning("[%s] replan refused: %s", plan.bot, e)
        plan.status = "failed"
        return False
    new_subtask.replans = failed_subtask.replans + 1
    # A replan may change the approach, never the goalposts: L3 rewrote kill
    # criteria into verifier-dodging synonyms in war-test round 2. Carry the
    # original criterion through verbatim — with ONE evidence-gated exception
    # (finding D2): if the original criterion is PROVABLY impossible (targets
    # a position outside the generated world) and the replacement is not,
    # accept the replacement. Scout burned a whole plan on "air at y=-43".
    if (failed_subtask.criteria or "").strip():
        proposed = (new_subtask.criteria or "").strip()
        if proposed and proposed != failed_subtask.criteria.strip():
            impossible = _criterion_impossible(plan.bot, failed_subtask.criteria)
            if impossible and not _criterion_impossible(plan.bot, proposed):
                log.info("[%s] replan criteria replacement ACCEPTED — original impossible: %s (%r -> %r)",
                         plan.bot, impossible, failed_subtask.criteria, proposed)
            else:
                log.info("[%s] replan tried to rewrite criteria (%r -> %r) — keeping original",
                         plan.bot, failed_subtask.criteria, new_subtask.criteria)
                new_subtask.criteria = failed_subtask.criteria
        else:
            new_subtask.criteria = failed_subtask.criteria
    for i, s in enumerate(plan.subtasks):
        if s.id == failed_subtask.id:
            plan.subtasks[i] = new_subtask
            break
    plan_store.write(plan)
    log.info("[%s] replanned subtask %d (replans=%d)",
             plan.bot, failed_subtask.id, new_subtask.replans)
    return True
