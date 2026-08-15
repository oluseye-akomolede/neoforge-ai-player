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

import datetime
import json
import logging
import os
import time
from typing import Any, Callable

import requests

import api
import l3_planner
import plan_memory
import plan_store
import skill_matcher
import telemetry
import trajectory_log
from criteria_eval import evaluate as evaluate_criteria
from plan_schema import Plan, PlanValidationError, Subtask

# Optional L2 translation layer (spec: l2-mcp-translation-layer). When set,
# directive normalization is delegated to the shared l2-mcp service; any
# failure falls back to the in-process copy below. Fail-open by design.
_L2_MCP_URL = os.getenv("L2_MCP_URL", "").rstrip("/")

log = logging.getLogger("aibot.orchestrator")

MAX_ATTEMPTS = 3
MAX_REPLANS_PER_SUBTASK = 2
MAX_SPEC_REFINES = 3

DispatchFn = Callable[[dict[str, Any]], str]
WorldStateFn = Callable[[], str]
OnPlanCreated = Callable[[Plan], None]
OnSubtaskStart = Callable[[Plan, Subtask], None]
OnSubtaskDone = Callable[[Plan, Subtask, bool], None]
OnFinalized = Callable[[Plan], None]


def _plan_from_skill(bot_name: str, task: str) -> Plan | None:
    """Deterministic plan-time skill match (Phase 0.5).

    When the task phrase unmistakably maps to a seed skill, build a
    single-subtask plan whose pre-baked directive is that SKILL — zero L3 calls,
    no decompose→collapse round-trip. A miss returns None and the caller falls
    through to L3 exactly as before.
    """
    directive = skill_matcher.match(task)
    if directive is None:
        return None
    skill_id = str(directive.get("target", ""))
    extra = directive.get("extra") if isinstance(directive.get("extra"), dict) else {}
    criteria = _skill_criteria(skill_id, extra)
    subtask = Subtask(
        id=1,
        description=task,
        criteria=criteria,
        status="pending",
        directives=[directive],
    )
    plan = Plan(
        task=task,
        bot=bot_name,
        created_at=datetime.datetime.utcnow().isoformat(),
        status="executing",
        subtasks=[subtask],
        current_subtask_id=1,
    )
    log.info("[%s] skill-match plan (%s, 0 LLM planning calls)", bot_name, skill_id)
    return plan


def _skill_criteria(skill_id: str, extra: dict[str, Any]) -> str:
    """A deterministic completion criterion for a matched skill.

    Material-output skills are grounded in the skill's real terminal item
    (same source _ground_skill_criteria uses at exec, so it will not rewrite
    this). Skills with no material output (goto_and_scan, resupply_network)
    fall back to the skill's own COMPLETED/FAILED dispatch signal.
    """
    count = str(extra.get("count") or "1")
    try:
        out = (api.skill_output(skill_id, **{k: str(v) for k, v in extra.items()}) or {}).get("output")
    except Exception:
        out = None
    if out and ":" in str(out):
        return f"inventory has {count} {out}"
    return "skill completes successfully"


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

    # Phase 0: plan-template memory — replay a proven SKILL-only plan for a
    # near-identical past task (exact normalized match, count substituted).
    # This is the only "0 LLM call" planning path: the deterministic
    # fast-planner shim is retired (v14), so every fresh task flows through L3
    # and raw-directive plans are never replayed.
    plan = plan_memory.lookup(bot_name, task)
    if plan is not None:
        log.info("[%s] plan-memory reuse (0 LLM planning calls)", bot_name)
    if plan is None:
        # Phase 0.5: deterministic skill match — a skill-covered task becomes a
        # single SKILL directive, skipping the L3 decompose→collapse round-trip.
        plan = _plan_from_skill(bot_name, task)
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
            trajectory_log.log_plan_close(
                bot=bot_name, plan_ref=plan.created_at, status=plan.status,
                task=task, subtasks_total=0, subtasks_complete=0,
            )
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
    telemetry.push(bot_name, "plan",
                   f"plan: {len(plan.subtasks)} subtasks for '{task[:80]}'")
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
            telemetry.push(bot_name, "subtask",
                           f"subtask {subtask.id}/{len(plan.subtasks)}: "
                           f"{subtask.description[:100]} | needs: {subtask.criteria[:80]}")
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
    trajectory_log.log_plan_close(
        bot=plan.bot, plan_ref=plan.created_at, status=plan.status,
        task=plan.task,
        subtasks_total=len(plan.subtasks),
        subtasks_complete=sum(1 for s in plan.subtasks if s.status == "complete"),
    )
    telemetry.push(bot_name, "done" if plan.status == "complete" else "fail",
                   f"plan finalized: {plan.status}")
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


def _is_spec_rejection(result_text: str) -> bool:
    """True if a SKILL dispatch failed because the mod REJECTED its inline spec
    (a validator problem L3 can fix), as opposed to a runtime failure of an
    already-registered skill (nothing to fix here)."""
    if not isinstance(result_text, str):
        return False
    return ("spec unparsable" in result_text
            or "spec rejected" in result_text
            or " rejected:" in result_text)


def _dispatch_skill_with_refine(d: dict[str, Any], dispatch_fn: DispatchFn,
                                model: str, bot_name: str) -> str:
    """Dispatch a SKILL directive carrying an inline spec. On a validator
    rejection, feed the joined error back to L3 (refine_skill) to fix the spec
    and re-dispatch, up to MAX_SPEC_REFINES times. Falls back to the raw result
    when the spec can't be extracted or L3 gives up — never worse than the
    existing single-shot path."""
    result = dispatch_fn(d)
    for _ in range(MAX_SPEC_REFINES):
        if not _is_spec_rejection(result):
            return result
        extra = d.get("extra")
        spec = extra.get("spec") if isinstance(extra, dict) else None
        if not isinstance(spec, str):
            # No inline spec string to fix (shouldn't happen for a proposal).
            return result
        error = result.replace("FAILED SKILL", "", 1).strip() or result
        fixed = l3_planner.refine_skill(model, bot_name, spec, error)
        if fixed is None:
            log.info("[%s] L3 could not fix rejected skill spec; keeping raw result",
                     bot_name)
            return result
        new_d = {"kind": "SKILL",
                 "target": d.get("target") or "proposed",
                 "extra": {"spec": fixed, "register": True}}
        # Re-normalize through _repair_directive so the mod's string contract
        # (spec → JSON string, register → "true") is re-applied to the fix.
        d = _repair_directive(new_d, bot_name, None)
        log.info("[%s] skill spec refine — retrying: %s", bot_name, error[:100])
        result = dispatch_fn(d)
    return result


def _step(plan: Plan, subtask: Subtask, model: str,
          dispatch_fn: DispatchFn, world_state_fn: WorldStateFn,
          dim_list: list[str] | None = None) -> bool:
    """Drive one subtask through one attempt. Returns False if the plan must abort."""
    # Replay path: a subtask that arrived with pre-baked directives (plan-memory
    # SKILL-only replay) on its first attempt skips the L3 exec call entirely.
    # Retries (attempts > 0) fall through to L3 so failures get intelligent
    # handling.
    if subtask.directives and subtask.attempts == 0 and not subtask.error:
        directives = list(subtask.directives)
        exec_call_id = None
        log.info("[%s] subtask %d dispatching pre-baked directives (0 LLM calls)",
                 plan.bot, subtask.id)
    else:
        # Phase 2 exec
        exec_call_id = None
        try:
            directives, exec_call_id = l3_planner.call_exec(
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

    # Prepend CHANNEL directives for any material shortfall (BUILD needs
    # and inventory criteria alike).
    directives = _provision_materials(plan.bot, directives, subtask.criteria or "")

    # Ground block-at criteria in the actual BUILD orders (finding D1):
    # deterministic derivation, not an LLM rewrite, so the anti-laundering
    # guarantee is untouched.
    derived = _derive_build_criteria(subtask, directives)
    if derived and derived != subtask.criteria:
        log.info("[%s] criteria grounded from BUILD directives: %r -> %r",
                 plan.bot, subtask.criteria, derived)
        subtask.criteria = derived

    # Ground an inventory criterion in the SKILL's actual output (v13): a
    # skill-covered subtask completes with what the skill holds, not the input
    # L3 hallucinated. Runs after build grounding (mutually exclusive kinds).
    grounded = _ground_skill_criteria(subtask, directives)
    if grounded and grounded != subtask.criteria:
        log.info("[%s] criteria grounded from SKILL output: %r -> %r",
                 plan.bot, subtask.criteria, grounded)
        subtask.criteria = grounded

    subtask.status = "executing"
    subtask.directives = list(directives)
    plan_store.write(plan)

    # Dispatch each directive via L1. A SKILL proposal carrying an inline spec
    # goes through the validate→refine loop so a mod-side validator rejection
    # is fed back to L3 and the spec is corrected in place before retrying.
    last_result = ""
    for d in directives:
        try:
            if (str(d.get("kind", "")).upper() == "SKILL"
                    and isinstance(d.get("extra"), dict)
                    and d["extra"].get("spec") is not None):
                last_result = _dispatch_skill_with_refine(
                    d, dispatch_fn, model, plan.bot)
            else:
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
    # The exact reason string the evaluator produced — the line that has
    # explained every campaign failure this project, now visible in-game.
    telemetry.push(plan.bot, "criteria" if satisfied else "criteria_fail",
                   f"[{strategy}] {reason}")

    # v11 R1: correlate this deterministic outcome to the exec call that
    # produced the directives (plan-memory replay subtasks had no L3 call).
    if exec_call_id:
        trajectory_log.log_outcome(
            call_id=exec_call_id, bot=plan.bot, phase="exec",
            plan_ref=plan.created_at, subtask_id=subtask.id,
            satisfied=satisfied, strategy=strategy, reason=reason,
        )

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

    # L4 trigger: attempts exhausted. The system used to replan blindly;
    # now the failure is shown to the player first. A free-text ruling
    # becomes guidance in the replan prompt (it rides subtask.error into
    # the next EXEC call). Timeout falls back to the blind replan.
    import escalation
    ruling = escalation.ask(
        plan.bot, "attempts_exhausted",
        f"Subtask {subtask.id} failed {MAX_ATTEMPTS}x: "
        f"{subtask.description[:80]} — last error: {str(reason)[:80]}",
        options=["replan", "skip subtask", "abort plan"], timeout=90)
    if ruling.get("answered"):
        choice = str(ruling.get("text", "")).strip()
        if choice == "abort plan":
            plan.status = "failed"
            plan_store.write(plan)
            return False
        if choice == "skip subtask":
            subtask.status = "complete"
            subtask.error = "skipped by player ruling"
            plan.advance()
            plan_store.write(plan)
            return True
        if choice and choice != "replan":
            # The overlay may send a JSON envelope: the player EDITED the
            # failing directive field-by-field. The edit becomes explicit
            # replan guidance — "use exactly this directive".
            import json as _json
            try:
                env = _json.loads(choice)
                parts = []
                if isinstance(env, dict):
                    if env.get("directive"):
                        parts.append("player corrected the directive to: "
                                     + _json.dumps(env["directive"]))
                    if env.get("note"):
                        parts.append(str(env["note"]))
                if parts:
                    choice = " | ".join(parts)
            except (ValueError, TypeError):
                pass
            subtask.error = f"{reason} | player guidance: {choice}"
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
from criteria_eval import _BLOCK_PATTERN, _CLAUSE_SPLIT, _INVENTORY_PATTERN  # shared criterion grammar


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


# Items whose only natural source is an Overworld ore — unobtainable by mining
# in the Nether/End. Gold is deliberately absent (nether gold ore drops it).
_OVERWORLD_ONLY_ITEMS = {
    "minecraft:diamond", "minecraft:diamond_ore", "minecraft:deepslate_diamond_ore",
    "minecraft:emerald", "minecraft:emerald_ore", "minecraft:deepslate_emerald_ore",
    "minecraft:coal", "minecraft:coal_ore", "minecraft:deepslate_coal_ore",
    "minecraft:iron_ingot", "minecraft:iron_ore", "minecraft:deepslate_iron_ore",
    "minecraft:copper_ingot", "minecraft:copper_ore", "minecraft:deepslate_copper_ore",
    "minecraft:lapis_lazuli", "minecraft:lapis_ore", "minecraft:deepslate_lapis_ore",
    "minecraft:redstone", "minecraft:redstone_ore", "minecraft:deepslate_redstone_ore",
}


def _current_dimension(bot_name: str) -> str:
    try:
        return api.status(bot_name).get("dimension", "")
    except Exception:
        return ""


def _criterion_impossible(bot_name: str, criteria: str) -> str | None:
    """Reason string if a criterion is provably impossible, else None.

    Two evidence classes: a block-at clause targeting a void position (outside
    the generated world), or an inventory clause demanding an Overworld-only
    item while the bot stands in the Nether/End (diamond-in-the-Nether loops).
    """
    for clause in _CLAUSE_SPLIT.split(criteria or ""):
        m = _BLOCK_PATTERN.search(clause)
        if m:
            bx, by, bz = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if _probe_block(bot_name, bx, by, bz) == "minecraft:void_air":
                return f"({bx},{by},{bz}) is outside the world"
        m = _INVENTORY_PATTERN.search(clause)
        if m:
            item_id = m.group(2)
            if ":" not in item_id:
                item_id = f"minecraft:{item_id}"
            if item_id in _OVERWORLD_ONLY_ITEMS:
                dim = _current_dimension(bot_name)
                if dim and dim != "minecraft:overworld":
                    return f"{item_id} is Overworld-only, but bot is in {dim}"
    return None


def _blueprint_block_count(target: str, extra: dict) -> int:
    """Approximate blocks a blueprint consumes (for material pre-provisioning)."""
    size = int(extra.get("size", extra.get("length", extra.get("width", 0)) or 0) or 0)
    height = int(extra.get("height", 0) or 0)
    t = target.lower()
    if t == "wall":
        return max(size, 9) * max(height, 3)
    if t == "tower":
        h = height or size or 8
        return max(h, 3) * 8 + 9
    if t == "platform":
        return max(size, 7) ** 2
    if t == "shelter":
        return 96
    if t == "farm":
        return 49
    return 0  # clear and unknowns consume nothing


def _provision_materials(bot_name: str, directives: list[dict],
                         criteria: str = "") -> list[dict]:
    """Deterministic dependency resolution (round-5 finding: L3 issues quartz
    BUILD orders with empty hands, or hallucinates acquisition recipes like
    smelting netherrack into quartz). Sum each BUILD's material need, check
    inventory, and prepend a CHANNEL for any shortfall — search-then-channel
    enforced by L2, not hoped for from L3."""
    # A SKILL directive covers the whole subtask end-to-end and its leaves own
    # acquisition (SmeltBehavior conjures inputs via XP, etc.). Provisioning a
    # skill-covered subtask just channels a bogus item the skill would have
    # produced itself — skip it.
    if any(str(d.get("kind", "")).upper() == "SKILL" for d in directives):
        return directives
    needs: dict[str, int] = {}
    for d in directives:
        if str(d.get("kind", "")).upper() != "BUILD":
            continue
        target = str(d.get("target", "")).lower()
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        n = _blueprint_block_count(target, extra)
        if n <= 0:
            continue
        material = str(extra.get("material", "")).strip()
        if not material:
            continue
        if ":" not in material:
            material = "minecraft:" + material
        needs[material] = needs.get(material, 0) + n
    # Inventory criteria are material requirements too (round-6 finding 26:
    # "collect 64 quartz_block" subtasks carry no BUILD directive, so the
    # BUILD-keyed provisioning never fired and Forge/Mystic starved).
    from criteria_eval import _INVENTORY_PATTERN
    for clause in _CLAUSE_SPLIT.split(criteria or ""):
        m = _INVENTORY_PATTERN.search(clause)
        if not m:
            continue
        need, item = int(m.group(1)), m.group(2)
        if ":" not in item:
            item = "minecraft:" + item
        from criteria_eval import ITEM_SYNONYMS
        item = ITEM_SYNONYMS.get(item, item)
        needs[item] = max(needs.get(item, 0), need)
    if not needs:
        return directives
    try:
        # Effective holdings (carried + vault) — provisioning must not
        # re-channel material the bot already owns in its vault.
        inv = api.effective_inventory(bot_name) or {}
        owned: dict[str, int] = {}
        for row in inv.get("inventory", []):
            owned[row.get("item", "")] = owned.get(row.get("item", ""), 0) + int(row.get("count", 0))
    except Exception:
        return directives  # can't check — don't guess
    prepend = []
    for material, needed in needs.items():
        short = needed - owned.get(material, 0)
        if short > 0:
            log.info("[%s] material pre-provision: %d more %s needed — channeling in chunks",
                     bot_name, short, material)
            # Chunked: one 240-block channel is ~12 minutes of uninterruptible
            # ritual (round-8 finding: killed Mystic's plan through attempt
            # timeouts). 64-block chunks complete in ~1 min each and partial
            # progress survives a failed attempt.
            while short > 0:
                chunk = min(short, 64)
                prepend.append({"kind": "CHANNEL", "target": material, "count": chunk})
                short -= chunk
    return prepend + directives


def _derive_build_criteria(subtask: Subtask, directives: list[dict]) -> str | None:
    """Ground a block-at criterion in the ACTUAL build orders (finding D1):
    PLAN-time criteria imagine coordinates; the emitted BUILD directives are
    the truth about where material will be placed. Every blueprint places its
    origin block, so 'block at (origin) is (material)' is exact."""
    if not _BLOCK_PATTERN.search(subtask.criteria or ""):
        return None
    # keyed by coordinate: overlapping builds (tower on wall corner) would
    # otherwise demand two different blocks at one position — last build wins
    clauses: dict[tuple, str] = {}
    for d in directives:
        if str(d.get("kind", "")).upper() != "BUILD":
            continue
        x, y, z = int(d.get("x", 0) or 0), int(d.get("y", 0) or 0), int(d.get("z", 0) or 0)
        if x == 0 and y == 0 and z == 0:
            continue  # build-at-bot: origin unknown at dispatch time
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        if str(d.get("target", "")).lower() in ("clear", "excavate", "dig"):
            # Excavation is verified by air at the pocket's center
            size = int(extra.get("size", 23) or 23)
            cx, cy, cz = x + size // 2, y + 1, z + size // 2
            clauses[(cx, cy, cz)] = f"block at ({cx},{cy},{cz}) is minecraft:air"
            continue
        material = str(extra.get("material", "minecraft:cobblestone"))
        if ":" not in material:
            material = "minecraft:" + material
        clauses[(x, y, z)] = f"block at ({x},{y},{z}) is {material}"
    return " AND ".join(clauses.values()) if clauses else None


# ── Skill-output grounding (v13) ───────────────────────────────────────────
# A skill-covered subtask completes with the item the skill ends up *holding*,
# not the input L3 hallucinated into the criterion ("inventory has 8
# minecraft:iron_ore_blocks" when mine_and_smelt actually yields
# minecraft:iron_ingot). The mod resolves the output from the skill's node
# tree against its own smelt/drop tables; the agent only checks which criterion
# items are real. Deterministic both halves — no LLM judgment.

_real_item_cache: dict[str, bool] = {}


def _is_real_item(item_id: str) -> bool:
    """True if the mod's item registry contains item_id (exact). Fail-open:
    a registry error returns True (assume real) so grounding can never rewrite
    a criterion onto the wrong item on a transient blip."""
    if item_id in _real_item_cache:
        return _real_item_cache[item_id]
    real = True
    try:
        resp = api.server_items(query=item_id)
        real = item_id in (resp or {}).get("items", [])
    except Exception:
        real = True
    _real_item_cache[item_id] = real
    return real


def _ground_skill_criteria(subtask: Subtask, directives: list[dict]) -> str | None:
    """Rewrite a hallucinated inventory criterion to the SKILL's real output.

    Returns the rewritten criteria string when at least one clause changed, else
    None. Mirrors `_derive_build_criteria`: a deterministic grounding, not an
    LLM rewrite, so the anti-laundering guarantee is untouched."""
    skill_d = next(
        (d for d in directives if str(d.get("kind", "")).upper() == "SKILL"),
        None,
    )
    if skill_d is None:
        return None
    skill_id = str(skill_d.get("target", "")).strip()
    extra = skill_d.get("extra") if isinstance(skill_d.get("extra"), dict) else {}
    if not skill_id:
        return None
    try:
        resp = api.skill_output(skill_id, **{k: str(v) for k, v in extra.items()})
    except Exception as e:
        log.debug("skill output resolve failed (%s): %s", skill_id, e)
        return None
    output = (resp or {}).get("output")
    if not output:
        return None

    from criteria_eval import _INVENTORY_PATTERN, ITEM_SYNONYMS

    rewritten: list[str] = []
    changed = False
    for clause in _CLAUSE_SPLIT.split(subtask.criteria or ""):
        m = _INVENTORY_PATTERN.search(clause)
        if not m:
            rewritten.append(clause)
            continue
        need, item = int(m.group(1)), m.group(2)
        if ":" not in item:
            item = "minecraft:" + item
        item = ITEM_SYNONYMS.get(item, item)
        if item == output or _is_real_item(item):
            rewritten.append(clause)
            continue
        rewritten.append(f"inventory has {need} {output}")
        changed = True
    return " AND ".join(rewritten) if changed else None


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
    "excavate": "clear",
    "dig": "clear",
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
                # L4 seam: l2-mcp DETECTS ambiguity and used to guess anyway
                # — detection without a recipient. The player is the
                # recipient now: candidates go to the inbox, and the ruling
                # replaces the guess. Timeout falls back to the old guess.
                if any(str(f).startswith("ambiguous_item") for f in flags):
                    candidates = ((nd.get("extra") or {}).get("item_candidates")
                                  or [])[:6]
                    if candidates:
                        import escalation
                        ruling = escalation.ask(
                            bot_name, "ambiguous_item",
                            f"'{nd.get('target')}' is ambiguous for {nd.get('kind')}"
                            f" — which did you mean?",
                            options=list(candidates), timeout=90)
                        if ruling.get("answered") \
                                and ruling.get("action") in ("choose", "answer") \
                                and ruling.get("text"):
                            nd["target"] = ruling["text"]
                            log.info("[%s] L4 resolved ambiguity -> %s",
                                     bot_name, nd["target"])
                return nd
        except Exception as e:
            log.debug("l2-mcp normalize bypass (%s)", e)
    kind = str(d.get("kind", "")).upper()
    d["kind"] = kind
    if kind == "EQUIP":
        d["kind"] = "EQUIP_ALL"

    if kind == "SKILL":
        # L3 proposes a new skill with an inline spec. The mod's extra map is
        # Map<String,String> (SkillBehavior.resolveSpec reads `spec` as a JSON
        # string), so normalize an ergonomic nested-object spec + boolean
        # register down to the string contract. A pre-serialized spec passes
        # through unchanged.
        #
        # The prompt invites a BARE node tree ({"type":"sequence","children":…
        # }); SkillSpec.parse requires the full contract {"id", "nodes": {tree}}.
        # Wrap the bare form so the mod accepts it, using the directive's
        # target as the skill id (a spec-provided id wins when present).
        extra = d.get("extra")
        if isinstance(extra, dict):
            spec = extra.get("spec")
            if isinstance(spec, dict):
                if "nodes" not in spec:
                    spec_id = str(spec.get("id") or d.get("target") or "proposed")
                    spec = {"id": spec_id,
                            "nodes": {k: v for k, v in spec.items() if k != "id"}}
                    log.info("[%s] wrapped proposed skill spec -> %s",
                             bot_name, spec_id)
                extra["spec"] = json.dumps(spec)
            if "register" in extra and not isinstance(extra["register"], str):
                extra["register"] = "true" if extra["register"] else "false"

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
    telemetry.push(plan.bot, "replan",
                   f"replanning subtask {failed_subtask.id} "
                   f"(attempt {failed_subtask.replans + 1}): {str(failed_subtask.error)[:100]}")
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
                # L4 trigger: the evidence gate says the original criterion is
                # provably impossible — but moving a goalpost is the player's
                # call to veto. Timeout accepts (old behavior); only an
                # explicit "keep original" blocks the replacement.
                import escalation
                ruling = escalation.ask(
                    plan.bot, "impossible_criteria",
                    f"Criterion provably impossible ({impossible}): "
                    f"'{failed_subtask.criteria[:70]}' — replace with '{proposed[:70]}'?",
                    options=["accept replacement", "keep original"], timeout=90)
                if ruling.get("answered") and ruling.get("text") == "keep original":
                    log.info("[%s] L4 vetoed criteria replacement — keeping original", plan.bot)
                    new_subtask.criteria = failed_subtask.criteria
                else:
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
