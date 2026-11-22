"""L3 spec-driven planning calls for aiplayer-mod bots.

Three call types:
  call_plan      — Phase 1, once per task, produces a Plan
  call_exec      — Phase 2, per subtask, produces directives
  call_replan    — fallback when a subtask exhausts retries

Reuses brain.ollama_lock for GPU serialization. When llm-gateway is
in front of Ollama, requests still go through OLLAMA_URL — the
gateway's Ollama-compat /api/chat handles them transparently.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import time
from typing import Any

import requests

import api
import trajectory_log
from brain import ollama_lock
from config import (OLLAMA_URL, TruncatedAnswer, answer_text,
                     ensure_not_truncated, think_field)
from plan_schema import Plan, PlanValidationError, Subtask, validate_plan_dict, validate_subtask_dict
# One source of truth for the script API surface: the L3 script prompt and the
# legacy planner's script section must not drift apart (gap seen live 2026-11-21).
from planner import SCRIPT_SURFACE as _SCRIPT_SURFACE
from planner import script_mode

log = logging.getLogger("aibot.l3-planner")


class PlanClarification(Exception):
    """L3 declined to plan: the task needs clarifying, or is impossible.

    Carries `kind` ("clarify" | "refuse") and a short `reason` the bot says
    to the player in chat. Distinct from PlanValidationError, which means the
    model produced a malformed plan rather than a deliberate refusal."""

    def __init__(self, kind: str, reason: str):
        super().__init__(f"L3 {kind}: {reason}")
        self.kind = kind
        self.reason = reason


BOT_PERSONAS = {
    "axiom":  "generalist; plans flexibly across any task domain",
    "forge":  "builder; plans in terms of materials, coordinates, construction sequences",
    "mystic": "mage; plans around enchantments, potions, magical resources",
    "scout":  "explorer; plans in terms of movement, mapping, resource discovery",
    "tiller": "farmer; plans around crop cycles, soil, water, harvest sequences",
}

# Default dimension list if the mod API isn't reachable / hasn't been queried.
# Real list is fetched at orchestrator-call time and overrides this.
_DEFAULT_DIMENSIONS = [
    "minecraft:overworld",
    "minecraft:the_nether",
    "minecraft:the_end",
]

_PRIMARY_DIMS = {"minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"}

# Single HTTP timeout for every L3 ollama call. 32b (19 GB) cold-loads in ~5m
# on the V100 pair — llama-server startup + CUDA-graph capture across the
# tensor-parallel split dominates, not the weight copy. 120s used to abort the
# load mid-flight on the first call after a pod restart (the agent's read
# timeout closed the connection, which cancelled the in-progress load). 420s
# rides out a full cold start; warm calls are unaffected.
_OLLAMA_TIMEOUT = 420.0


def _dim_lines(dimensions: list[str] | None) -> str:
    """Render the dimension list with usage annotations. War-test finding #4:
    an unannotated list led L3 to stage crafting inside ae2:spatial_storage."""
    dims = dimensions or _DEFAULT_DIMENSIONS
    primary = [d for d in dims if d in _PRIMARY_DIMS]
    exotic = [d for d in dims if d not in _PRIMARY_DIMS]
    lines = [f"  - {d}" for d in primary]
    lines += [f"  - {d} (special-purpose — do NOT travel here unless the task names it)"
              for d in exotic]
    return "\n".join(lines)


# ── Skill catalog (v10) ─────────────────────────────────────────────────────

_skills_cache: tuple[float, str] | None = None
_SKILLS_CACHE_TTL = 60.0


def _skills_lines() -> str:
    """Render the registered skill catalog from GET /skills, cached briefly.

    The catalog is server-global and changes only via runtime self-expansion,
    so a short TTL avoids a GET per subtask while still picking up new skills.
    Returns "" when the API is unreachable (L3 still emits raw directives)."""
    global _skills_cache
    now = time.monotonic()
    if _skills_cache is not None and now - _skills_cache[0] < _SKILLS_CACHE_TTL:
        return _skills_cache[1]
    text = ""
    try:
        entries = (api.skills() or {}).get("skills") or []
        lines = []
        for s in entries:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id", "?"))
            desc = str(s.get("description", "") or "").strip()
            params = s.get("params") or {}
            param_str = (", ".join(f"{k}:{v}" for k, v in params.items())
                         if isinstance(params, dict) else "")
            line = f"    {sid}"
            if desc:
                line += f" — {desc}"
            if param_str:
                line += f"  [params: {param_str}]"
            lines.append(line)
        text = "\n".join(lines)
    except Exception as e:  # noqa: BLE001 — best-effort enrichment
        log.debug("skills fetch failed: %s", e)
    _skills_cache = (now, text)
    return text


# ── Post-EXEC skill collapse (deterministic backstop) ──────────────────────
#
# L3 is asked to prefer SKILL, but a small model may still hand-decompose a
# skill-covered subtask into its raw directive sequence. This backstop detects
# that case and collapses the raw sequence into a single SKILL directive, so the
# v10 "skills first, directives fallback" contract holds regardless of model
# behavior. It is deliberately conservative:
#   - Only the five curated seed skills are matched (their kind signature + param
#     names are fixed here; self-expanded skills fall through to their raw
#     directives, which is always safe).
#   - The match is an EXACT kind-sequence match (order + kinds). Any same-shape
#     raw pair is re-routed to the skill, but a bad param is caught by the
#     skill's verify predicate and the orchestrator retries/replans.

# seed skill id -> (ordered directive kind signature, param names to extract)
_SEED_SKILLS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "mine_and_smelt": (("MINE", "SMELT"), ("target", "count")),
    "goto_and_scan": (("TELEPORT", "WIDE_SEARCH"), ("x", "y", "z", "target")),
    "search_and_loot": (("AREA_LOOT", "STORE_ALL"), ("x", "y", "z", "radius")),
    "harvest_and_store": (("FARM", "STORE_ALL"), ("crop", "count")),
    "resupply_network": (("CHANNEL", "SEND_ITEM"), ("item", "count", "to")),
    "summon_vehicle": (("REQUISITION", "MOUNT_VEHICLE"), ("vehicle",)),
    "channel_gun": (("CHANNEL",), ("gun",)),
    "fuse_generator": (("FUSE_BLOCK",), ()),
    "fuse_reactor": (("FUSE_BLOCK",), ()),
    "fuse_battery": (("FUSE_BLOCK",), ()),
    "fuse_simchamber": (("FUSE_BLOCK",), ()),
}


def _build_skill_extra(param_names, directives: list[dict]) -> dict[str, str]:
    """Map raw directives back onto a skill's param names. Conservative: a param
    it cannot map is omitted (the skill's own verify predicate catches a bad run)."""
    def find(*kinds: str):
        for d in directives:
            if str(d.get("kind", "")).upper() in kinds:
                return d
        return None

    extra: dict[str, str] = {}
    for name in param_names:
        n = str(name).lower()
        if n == "count":
            for d in directives:
                if d.get("count") is not None:
                    extra[name] = str(d["count"])
                    break
        elif n == "target":
            # first directive that actually carries a target (MINE for
            # mine_and_smelt; WIDE_SEARCH for goto_and_scan whose TELEPORT has none)
            for d in directives:
                if d.get("target"):
                    extra[name] = str(d["target"])
                    break
        elif n == "smelt":
            d = find("SMELT")
            extra[name] = str(d.get("target", "")) if d else ""
        elif n == "item":
            d = find("CHANNEL", "SEND_ITEM", "CONTAINER_SEARCH", "CONTAINER_WITHDRAW")
            extra[name] = str(d.get("target", "")) if d else ""
        elif n == "crop":
            d = find("FARM")
            extra[name] = str(d.get("target", "")) if d else ""
        elif n == "to":
            d = find("SEND_ITEM")
            extra[name] = str(d.get("target", "")) if d else ""
        elif n in ("x", "y", "z"):
            d = find("TELEPORT", "GOTO", "AREA_LOOT")
            extra[name] = str(d.get(n, "")) if d else ""
        elif n == "radius":
            d = find("AREA_LOOT", "WIDE_SEARCH")
            extra[name] = str(d.get("radius", "")) if d else ""
        # unknown param name -> omitted (SkillParams leaves ${name} visible)
    return extra


# DirectiveType enum (mod) — the kinds a declarative skill leaf may use. The
# shim refuses to synthesize a skill from any kind outside this set: EQUIP_ALL,
# EQUIP, DROP, VAULT_STORE/WITHDRAW, PROVISION_TERMINAL and ASK_PLAYER are
# agent-side conveniences, not mod directives, and would fail SkillValidator.
_VALID_DIRECTIVE_KINDS = frozenset({
    "MINE", "GATHER", "GOTO", "FOLLOW", "COMBAT", "CRAFT", "SMELT", "ENCHANT",
    "BREW", "CHANNEL", "SEND_ITEM", "BUILD", "FARM", "CONTAINER_PLACE",
    "CONTAINER_SEARCH", "CONTAINER_STORE", "CONTAINER_WITHDRAW", "TELEPORT",
    "IDLE", "PATROL", "WIDE_SEARCH", "LOCATE", "STORE_ALL", "ME_STORE",
    "ME_WITHDRAW", "CRAFT_REQUEST", "MEDITATE", "CULTIVATE",
    "MOUNT_VEHICLE", "DISMOUNT_VEHICLE", "DRIVE_VEHICLE", "REQUISITION",
    "FUSE_BLOCK", "MANAGE_FUSION", "UNFUSE_BLOCK",
})

# Valid kinds that are nonetheless context-specific (a hardcoded coordinate,
# a named structure, a followed/patrolled target) — a frozen skill replaying
# them verbatim is wrong, so the shim will not synthesize from them.
_NON_REUSABLE_KINDS = frozenset({
    "TELEPORT", "GOTO", "LOCATE", "PATROL", "FOLLOW", "BUILD", "IDLE",
    "DRIVE_VEHICLE",
})


def _directive_to_node(d: dict) -> dict:
    """One raw L3 directive → a declarative DIRECTIVE leaf. Numeric fields are
    stringified: SkillNode.parse reads leaves as strings, SkillBehavior re-parses
    at execution time."""
    node = {"type": "directive", "kind": str(d.get("kind", "")).upper()}
    for field in ("target", "count", "radius", "x", "y", "z"):
        v = d.get(field)
        if v is not None and str(v) != "":
            node[field] = str(v)
    extra = d.get("extra")
    if isinstance(extra, dict) and extra:
        node["extra"] = {k: str(v) for k, v in extra.items()}
    return node


def _synthesize_skill(directives: list[dict], kinds: tuple[str, ...]) -> dict | None:
    """Deterministic self-expansion: a bounded (2-3 leaf) sequence of valid,
    reusable directive kinds that matches NO seed is a routine L3 hand-expanded
    instead of proposing. Synthesize an inline SKILL for it (register:true) so
    the mod validates + registers it and a future identical task reuses it.

    Frozen, not parameterized: leaf targets/counts are baked in. Deliberate —
    the shim learns the exact routine it just ran, never an over-generalized
    one. Returns None when the sequence is not a candidate."""
    if len(directives) not in (2, 3):
        return None
    if any(k not in _VALID_DIRECTIVE_KINDS for k in kinds):
        return None
    if any(k in _NON_REUSABLE_KINDS for k in kinds):
        return None
    skill_id = "gen_" + "_".join(k.lower() for k in kinds)
    tree = {"type": "sequence", "children": [_directive_to_node(d) for d in directives]}
    log.info("skill-synthesize: %s -> %s (register)", kinds, skill_id)
    return {"kind": "SKILL", "target": skill_id,
            "extra": {"spec": tree, "register": True}}


def _collapse_to_skill(directives: list[dict]) -> list[dict]:
    """Collapse a raw directive sequence into a single SKILL directive: an exact
    seed match re-routes to that seed, otherwise a bounded reusable no-seed
    sequence is synthesized inline (register:true). Returns the input unchanged
    when neither applies."""
    if not directives:
        return directives
    kinds = tuple(str(d.get("kind", "")).upper() for d in directives)
    if "SKILL" in kinds:
        return directives  # already skill-directed
    for skill_id, (signature, param_names) in _SEED_SKILLS.items():
        if kinds == signature:
            extra = _build_skill_extra(param_names, directives)
            log.info("skill-collapse: %s -> SKILL %s (extra=%r)", kinds, skill_id, extra)
            return [{"kind": "SKILL", "target": skill_id, "extra": extra}]
    synthesized = _synthesize_skill(directives, kinds)
    if synthesized is not None:
        return [synthesized]
    return directives


# ── Phase 1: plan ──────────────────────────────────────────────────────────


_PLAN_SCRIPT_SECTION = """Choose between a STEP LIST and a SCRIPT:
- A step list is the default. Use it for one-shot goals that finish: "go to X",
  "craft 8 iron ingots", "dig a 3x3 hole here", "bring 16 wheat".
- For goals that REPEAT, WAIT on a condition, or REACT over time, and so never
  finish on their own — "keep the furnace fed", "store items whenever your
  inventory fills", "tell me when it gets dark" — answer with the plan JSON and
  set "wants_script": true (see the output schema). Do not write the script in
  this reply: a separate call asks for it, and only if you set the flag.
  A step list cannot express these; it runs once and ends.
- If a goal is clearly one-shot, use a step list even when it mentions a time
  word ("bring me X before dark" is still one-shot). If a goal could be read
  either way, it is your call.

A script is plain JavaScript for one tick, run every tick. Its API is exactly:
- api.do(action)      — queue one game action this tick
- api.say(text)       — speak in chat (rate limited)
- api.send(target, t) — send a chat message to another bot
- api.recall()        — the memory blob this tick started with (or null)
- api.remember(v)     — persist a STRING across ticks; read it back next tick
                        via api.recall(). One blob, 16 KiB, last write wins.
- api.log(level, t)   — write a line to the agent log ("info"/"warn"/...)
The world state is a read-only global named `snapshot`, NOT an api method:
  const s = snapshot;
  if (s) { /* s.self, s.bots, s.inventory, ... */ }
Do NOT call api.get_snapshot() or api.get_directive() — they do not exist, and
a call to a missing method throws and discards your whole script.
Return an array of actions (or [] to do nothing this tick). A script that
throws is discarded and the step-list path takes over.

Output schema (step list — the common case):
{
  "task": "<echo the task text>",
  "subtasks": [
    {
      "id": 1,
      "description": "...",
      "criteria": "..."
    },
    ...
  ]
}
(or, instead of the above, {"kind": "clarify"|"refuse", "reason": "..."})

Script flag — for a repeating/conditional goal ONLY (see WHEN TO ASK FOR A
SCRIPT above), add one boolean to the same object:

  "wants_script": true

Nothing else changes about this reply. Do NOT write the script here, and do
NOT add a "script" key — a separate call is made for the script if and only if
you set this flag. For a one-shot goal, omit the flag or set it false.

When you set "wants_script": true, "subtasks" may be empty or omitted: a goal
that never finishes has no steps, and the script is the work. Leave it out
rather than inventing a step to satisfy the shape."""


_PLAN_SYSTEM_PROMPT = """You are {bot_name}, an AI bot in Minecraft.
Persona: {persona}.

Your job RIGHT NOW is NOT to execute the task — it is to plan it.

Available dimensions on this server (you can subtask any of these; use exact ids):
{dimensions}

Decompose the task below into ordered atomic subtasks. For each subtask:
- A clear `description` of what to do
- An explicit `criteria` string — a condition observable in world state that
  proves this subtask is done (e.g. "inventory has 16 wheat", "bot at 100,64,-200",
  "block at 5,64,7 is oak_log", "bot in dimension minecraft:the_nether")

Criteria MUST use one of these machine-checkable forms whenever possible:
  - "inventory has <N> <item_id>"          (item possession)
  - "bot at (<x>, <y>, <z>)"               (position)
  - "bot in dimension <dimension_id>"       (dimension)
  - "killed <N> enemies"                    (combat kill count — verified
                                             against the bot's kill statistic)
  - "block at (<x>,<y>,<z>) is <block_id>"  (placed/changed block)
Free-text criteria cannot be verified and will be judged loosely — avoid them.

Construction rules (MANDATORY for fortresses, strongholds, bases):
- Build from minecraft:quartz_block ONLY. Terrain-native materials
  (netherrack, stone, dirt) are indistinguishable from the landscape —
  invisible to players and unverifiable by block checks. Acquire quartz by
  mining nether quartz ore and crafting, or by channeling quartz blocks.
- FIRST subtask after arrival MUST clear a pocket: excavate an open volume
  larger than the structure (BUILD blueprint "clear") — never embed walls
  inside solid terrain.

Reconnaissance: structures (end city, fortress, village, stronghold, mansion,
monument, and modded ones) are LOCATED, not searched for. A single subtask
"locate the nearest <structure> and travel to it" is correct and sufficient —
do not plan a sweep, a grid search, or an exploration phase to find one.
Coordinates a bot has already found appear in world state as known_locations.

Inventory model: each bot has 36 carried slots plus an UNBOUNDED vault.
Overflow pages to the vault automatically and BUILD withdraws from it as
needed, so you never need to plan around running out of space. "inventory
has N item" criteria count carried + vault together.

Criteria geometry rules (checked against the real world — violations fail):
- Block coordinates MUST be inside the world. The nether's build range is
  y 0..127; the overworld's is y -64..319. Never use negative y in the nether.
- A "block at" criterion must name a position INSIDE the volume a subtask
  actually builds, at the SAME y-level as the build origin — do not invent
  positions above, below, or beside the structure.

Constraints:
- Output ONLY JSON. No prose. No markdown fences.
- 1 to 6 subtasks. Break larger jobs into multiple submissions instead.
- Each subtask should map to 1-3 directives maximum.
- Your subtasks together MUST cover EVERY action clause in the task. If the
  task says prepare AND travel AND fight, all three must appear as subtasks —
  do not drop trailing clauses.
- If the task involves a dimension change (e.g. "to the nether"), the FIRST
  subtask MUST be a teleport to that dimension. Use the exact dimension id.

Registered skills (each runs end-to-end as ONE deterministic directive):
{skills}

When a registered skill above covers the ENTIRE task, plan exactly ONE subtask
for it: set the description to "Run skill <skill_id> with <param>=<value>, ..."
and the criteria to what that skill verifies (e.g. "inventory has 8
minecraft:iron_ingot"). Do NOT split a skill-covered task into its component
directives — the skill already sequences them. Fall back to raw subtasks only
when no skill fits.

When NO skill covers the task but the task is a bounded, reusable multi-step
routine (2-3 directive kinds in a fixed order, e.g. "equip then fight"), plan a
SINGLE subtask for the whole routine — do NOT split it into one-directive
subtasks. The exec layer can then synthesize a NEW skill for it inline. Split
into separate subtasks only when the steps are independent goals, not one routine.

Before planning, check the task against reality. Do NOT silently substitute a
different, doable-sounding task for one that was asked. If any part of the task
names something this server does not have, or asks for two mutually exclusive
things at once, you MUST decline — a plausible substitution is still a lie.

Return instead of a plan:
  - {{"kind": "clarify", "reason": "<one short question>"}} when the task is too
    vague to act on ("go get some stuff", "make it better") — ask what exactly
    is wanted, naming the ambiguity.
  - {{"kind": "refuse", "reason": "<one short why>"}} when the task is
    impossible here (something the server lacks), self-contradictory, or asks
    for two things at once that cannot both be done. Examples:
      * "fly to the moon" → refuse: there is no moon; the dimensions are
        overworld, nether, end.
      * "dig to bedrock at the same time as X" → refuse: two simultaneous
        actions.
      * "go get some stuff" → clarify: which stuff, and how much.
    Do NOT convert these into a nearby achievable goal (e.g. "go to the End"
    for "fly to the moon"). Naming the real goal is the whole point.
A fabricated plan is worse than a refusal: the player acts on it and it cannot
succeed. Keep the reason to one sentence, in the bot's voice.

{script_section}
"""


_SCRIPT_SYSTEM_PROMPT = """You are {bot_name}, a {persona}, writing ONE game script.

This is a script-only reply. The player's goal has already been planned; you
are writing the JavaScript that will run the goal every tick instead of a
step list.

{script_surface}

The world state is also a read-only global named `snapshot`, not an api method:

  const s = snapshot;              // may be undefined if none was sent
  if (s) {{ /* s.self, s.bots, s.inventory, ... */ }}

Do NOT call api.get_snapshot() or api.get_directive() — they do not exist,
and a call to a missing method throws and discards your whole script.

Do not try to report by returning a value: a script's top-level return value
is discarded. Use api.result(value) to report. A script that throws is
discarded and the step-list path takes over.

Skills you can call from an action:
{skills}

Write the whole script. Your ENTIRE reply must be one fenced block and nothing
else — no prose before or after, no JSON:

```js
// your javascript here
```

Multi-line JavaScript is expected and fine. Keep it under 64 KiB.
"""


def render_plan_prompt(bot_name: str, dimensions: str = "",
                       offered: bool | None = None) -> str:
    """Render the L3 plan prompt for one bot.

    `offered` is decided by the caller from `script_mode`, so there is one gate
    and one renderer: a test that wants to check what a non-offered bot is told
    calls THIS, and so exercises the same format call production uses. Passing
    None looks it up, which is what a caller outside the plan path wants.
    """
    if offered is None:
        offered, _why = script_mode(bot_name)
    return _PLAN_SYSTEM_PROMPT.format(
        bot_name=bot_name,
        persona=BOT_PERSONAS.get(bot_name, "generalist"),
        dimensions=dimensions,
        skills=_skills_lines(),
        script_section=_PLAN_SCRIPT_SECTION if offered else "")


def call_plan(model: str, bot_name: str, task: str,
              world_state_summary: str = "",
              dimensions: list[str] | None = None) -> Plan:
    persona = BOT_PERSONAS.get(bot_name, "generalist")
    log.info("[%s] L3 PLAN call — task: %s", bot_name, task[:60])
    dim_lines = _dim_lines(dimensions)
    # The invitation and the capability must agree: a bot not offered scripts is
    # not taught how to ask for one, so the model never spends a second call
    # learning that the surface is missing. call_plan ALSO refuses the fetch
    # below, because a prompt is not a contract.
    offered, why = script_mode(bot_name)
    sys_prompt = render_plan_prompt(
        bot_name, dimensions=dim_lines, offered=offered)
    user = f"World state: {world_state_summary}\n\nTask: {task}" if world_state_summary else task

    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                **think_field(),
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                # JSON mode, as before a2. The script is NOT requested here: a
                # script inside this reply would either have to be escaped into
                # a JSON string (which a 27B model does unreliably — it emitted
                # a literal newline at 15:57Z and lost the plan) or force JSON
                # mode off for every plan. Instead this call may set
                # wants_script, and only then is a second, non-JSON call made.
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": _PLAN_NUM_PREDICT},
            },
            timeout=_OLLAMA_TIMEOUT,
        )
    resp.raise_for_status()
    body = resp.json()
    # A length stop is decided BEFORE parsing, and before answer_text.
    #
    # answer_text raises TruncatedAnswer only when the content is EMPTY. A
    # reply cut mid-object has content -- the 2026-11-20 21:52Z trial sent
    # 92 chars of a valid plan, `{"task": "...", "subtasks": [`, and fell
    # through to json.loads, which reported "reply was not JSON (Expecting
    # value: line 3 column 16)". That message sends a reader to fix the prompt
    # when the prompt was fine and the budget was not.
    #
    # The same rule as the SCRIPT call's (G-3): a length stop means the reply
    # is not a usable answer, whatever it contains. check it first, always.
    if isinstance(body, dict) and body.get("done_reason") == "length":
        log.warning(
            "[%s] L3 PLAN reply stopped at the token limit (done_reason=length, "
            "eval_count=%s, %d chars of content) and is unusable as it stands; "
            "the budget was %d",
            bot_name, body.get("eval_count"),
            len((body.get("message") or {}).get("content") or ""),
            _PLAN_NUM_PREDICT)
        raise TruncatedAnswer(
            "PLAN call hit the token limit before finishing (done_reason=length, "
            "eval_count=%s)" % body.get("eval_count"))
    raw = _strip_codefence(answer_text(body))
    created_at = datetime.datetime.utcnow().isoformat()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        trajectory_log.log_call(
            phase="plan", bot=bot_name, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=None,
            world_state_summary=world_state_summary,
            plan_ref=created_at, parse_error=f"non-JSON: {e}",
        )
        log.warning("[%s] L3 PLAN reply was not JSON (%s); raw preview: %s",
                    bot_name, e, preview_reply(raw))
        raise PlanValidationError(f"L3 PLAN returned non-JSON: {e}") from e
    # Clarify/refuse: when the task cannot honestly be decomposed — it is too
    # vague to act on ("go get some stuff"), impossible on this server, or
    # self-contradictory — L3 returns a short reason for the player instead of
    # inventing a plan. Tiller's "go get some stuff" became a fabricated
    # loot-village + quartz-shelter plan; this is the honest exit.
    if isinstance(data, dict) and data.get("kind") in ("clarify", "refuse"):
        reason = str(data.get("reason") or "").strip()[:300]
        if not reason:
            reason = "I can't work out what you want — say it another way?"
        trajectory_log.log_call(
            phase="plan", bot=bot_name, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=data,
            world_state_summary=world_state_summary,
            plan_ref=created_at,
        )
        raise PlanClarification(str(data["kind"]), reason)
    try:
        validate_plan_dict(data, goal=task)
    except PlanValidationError as e:
        trajectory_log.log_call(
            phase="plan", bot=bot_name, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=None,
            world_state_summary=world_state_summary,
            plan_ref=created_at, parse_error=str(e),
        )
        raise
    trajectory_log.log_call(
        phase="plan", bot=bot_name, model=model,
        prompt_system=sys_prompt, prompt_user=user,
        response_raw=raw, parsed=data,
        world_state_summary=world_state_summary,
        plan_ref=created_at,
    )
    plan = Plan(
        task=data["task"],
        bot=bot_name,
        created_at=created_at,
        status="executing",
        # A script-signalling reply may carry no subtasks at all. Reading
        # `data["subtasks"]` there raised KeyError, and indexing it below would
        # too -- the goal never reached the SCRIPT call below. An empty list is
        # the honest representation: the plan has no steps because the script
        # is the work.
        subtasks=[Subtask.from_dict(s) for s in (data.get("subtasks") or [])],
        current_subtask_id=min((s["id"] for s in (data.get("subtasks") or [])),
                               default=1),
    )
    # The plan call may have flagged that this goal wants a script. Only then is
    # a second call made — a step-list goal makes exactly one call and its
    # reply shape is unchanged apart from the wants_script field itself.
    if data.get("wants_script") is True:
        # A prompt is not a contract. The plan prompt above already withholds
        # the invitation, but a model can set this flag from a stale cached
        # prompt or from habit, and a second call is the cost. Refusing to fetch
        # is not an error: the goal proceeds on the plan's steps, the same way a
        # stray `script` field is ignored rather than failed.
        if not offered:
            log.info("[%s] not fetching a script: %s", bot_name, why)
            return plan
        script = call_script(
            bot_name=bot_name, task=task, plan=data, model=model,
            world_state_summary=world_state_summary)
        # In memory only. Plan.to_dict() enumerates its fields explicitly, so
        # this attribute is not written to disk or read by the dashboard. That
        # guarantee rests on that enumeration: if to_dict ever switches to
        # asdict(), this field starts being persisted and must be excluded.
        if script:
            plan.script = script
    return plan


# ── Phase 2: exec ──────────────────────────────────────────────────────────


_EXEC_SYSTEM_PROMPT = """You are {bot_name}, executing a plan. Focus ONLY on the current subtask.

Full plan (context):
{plan_json}

Current subtask:
{subtask_json}

World state: {world_state}

Active dimensions on this server (use these EXACT ids when teleporting):
{dimensions}

Previous attempt error (if any): {error}

Emit one or more directives that, when executed, will satisfy the subtask's criteria.
Do NOT plan beyond this subtask — L2 advances the plan when criteria are met.

Output ONLY a JSON object (no prose, no fences):
{{
  "directives": [
    {{ "kind": "MINE", "target": "minecraft:iron_ore", "count": 16 }},
    ...
  ]
}}

SKILL REFERENCE (registered skills — pick one when it covers the subtask):
{skills}

FIRST, check the SKILL REFERENCE above. If a registered skill covers this entire
subtask end-to-end, emit exactly ONE directive of kind SKILL — do NOT hand-expand
the skill into its raw directive sequence. Skills are deterministic and
post-verified against world state, so a matching skill is always the better choice.

A skill covers a subtask ONLY when EVERY step in its description applies — never
just one. Each seed skill is a fixed two-step routine (e.g. "mine THEN smelt",
"farm THEN store", "conjure THEN send"). If the subtask asks for only ONE of
those steps, or pairs a step with a DIFFERENT second step (e.g. "mine then
store", "craft then store", "conjure then keep"), the skill does NOT cover it —
hand-expand the raw directives instead. Never drop or rename a step the subtask
requires just to fit a skill, and never repurpose a skill's parameter (e.g. a
"crop" slot is for crops, not planks or ingots).

Worked example — subtask "mine 8 iron ore and smelt into ingots" is covered by the
mine_and_smelt skill, so emit:
{{
  "directives": [
    {{ "kind": "SKILL", "target": "mine_and_smelt", "extra": {{ "target": "minecraft:iron_ore", "count": "8" }} }}
  ]
}}

RAW DIRECTIVE REFERENCE (fallback — use ONLY when NO skill above covers the subtask):

  MINE             — {{ "kind":"MINE", "target":"minecraft:iron_ore", "count":16 }}
  CRAFT            — {{ "kind":"CRAFT", "target":"minecraft:torch", "count":16 }}
  SMELT            — {{ "kind":"SMELT", "target":"minecraft:raw_iron", "count":16 }}
  CHANNEL          — {{ "kind":"CHANNEL", "target":"minecraft:diamond", "count":4 }}
                     (use when no recipe exists OR item must be transmuted via EMC)
                     GUNS: TaCZ guns are ONE item — never channel
                     tacz:modern_kinetic_gun; the target is the GUN ID
                     (tacz:ak47, tacz:m4a1 …) and Superb Warfare guns are
                     their item id (superbwarfare:hk_416). Prefer SKILL
                     channel_gun (gun + ammo) and SKILL channel_ammo
                     (target "ammo" = rounds for the gun the bot holds).
  ENCHANT          — {{ "kind":"ENCHANT", "target":"minecraft:iron_pickaxe", "extra":{{"tier":"max"}} }}
  BREW             — {{ "kind":"BREW", "target":"minecraft:potion_of_healing", "count":1 }}
  FARM             — {{ "kind":"FARM", "target":"minecraft:wheat", "count":32 }}
  BUILD            — {{ "kind":"BUILD", "target":"wall", "x":<int>, "y":<int>, "z":<int>, "extra":{{"material":"minecraft:netherrack","size":21,"height":8}} }}
                     target = blueprint name. ONLY these blueprints exist:
                       wall (size=length, height), tower (height, 3x3 footprint),
                       platform (size x size), shelter (5x5x4 hut), farm (7x7),
                       clear (EXCAVATES a size x height x size pocket — use FIRST
                       when building in solid terrain; no material needed).
                     There is NO gate/pillar/cube/keep blueprint — compose them
                     from walls and towers. x/y/z = world coords of build origin;
                     the material must already be in inventory (mine it first).
                     Fortress construction material MUST be minecraft:quartz_block
                     (terrain-native materials are invisible and unverifiable).
  COMBAT           — {{ "kind":"COMBAT", "target":"minecraft:zombie", "extra":{{"radius":16}} }}
  VAULT_STORE      — {{ "kind":"VAULT_STORE", "target":"minecraft:cobblestone", "count":64 }}
                     Pages carried items into the bot's UNBOUNDED vault. Omit
                     target to flush everything evictable. The vault is real
                     storage: items there still count toward "inventory has N
                     item" criteria, and BUILD pulls from it automatically.
                     You rarely need this — overflow pages itself.
  VAULT_WITHDRAW   — {{ "kind":"VAULT_WITHDRAW", "target":"minecraft:quartz_block", "count":64 }}
                     Pulls items from the vault back into carried inventory.
  DROP             — {{ "kind":"DROP", "target":"minecraft:rotten_flesh", "count":64 }}
                     Destroys items permanently. Prefer VAULT_STORE — the vault
                     is unbounded, so there is almost never a reason to DROP.
  EQUIP_ALL        — {{ "kind":"EQUIP_ALL" }}
                     Scans inventory and equips the best armor pieces, shield,
                     and weapon automatically. Use whenever the task says
                     "equip". There is NO per-item EQUIP directive.
  FOLLOW           — {{ "kind":"FOLLOW", "target":"<player_name>" }}
                     target may be a player name or "me"/"master"
                     (the unit follows whoever last commanded it); it gives up
                     if that player logs off, so it never freezes.
  GOTO             — {{ "kind":"GOTO", "x":<int>, "y":<int>, "z":<int> }}
                     (intra-dimension only; uses current dimension)
  TELEPORT         — {{ "kind":"TELEPORT", "x":<int>, "y":<int>, "z":<int>, "extra":{{"dimension":"<dim_id>"}} }}
                     CROSS-DIMENSION: dimension is REQUIRED. If you only know the
                     destination is "the nether", set dimension="minecraft:the_nether"
                     and use safe default coords like x=0,y=70,z=0 — the L1 layer
                     will land the bot on solid ground near those coords. NEVER
                     emit a TELEPORT with x=0,y=0,z=0 AND no dimension change.
  SEND_ITEM        — {{ "kind":"SEND_ITEM", "target":"<player>", "extra":{{"item":"minecraft:diamond","count":4}} }}
  CONTAINER_STORE  — {{ "kind":"CONTAINER_STORE", "target":"minecraft:iron_ingot", "count":64 }}
  CONTAINER_WITHDRAW — {{ "kind":"CONTAINER_WITHDRAW", "target":"minecraft:iron_ingot", "count":64 }}
  CONTAINER_PLACE  — {{ "kind":"CONTAINER_PLACE", "target":"minecraft:chest", "x":<int>, "y":<int>, "z":<int> }}
  CONTAINER_SEARCH — {{ "kind":"CONTAINER_SEARCH", "target":"minecraft:diamond", "count":5 }}
  LOCATE           — {{ "kind":"LOCATE", "target":"end_city", "extra":{{"travel":"true"}} }}
                     Finds the nearest STRUCTURE (end city, fortress, village,
                     stronghold, mansion, monument, modded structures) by asking
                     the world generator — one query, reaches ~1600 blocks.
                     USE THIS FOR STRUCTURES. WIDE_SEARCH cannot find them.
                     To GO to what you find, set "extra":{{"travel":"true"}} —
                     one directive that finds it AND lands the bot there.
                     Do NOT emit LOCATE then GOTO in the same subtask: every
                     directive in a subtask is written before any of them runs,
                     so you cannot know the coordinates yet and would be
                     guessing. Coordinates from a completed LOCATE appear in
                     world state as known_locations=[...] — a LATER subtask may
                     GOTO/TELEPORT those exact numbers.
                     The finding is written to the requesting player's TemPad
                     automatically so they can open a portal to it — you do NOT
                     need to set share_with. Set
                     "extra":{{"share_with":"<player>"}} only to send it to a
                     DIFFERENT player than the one who gave the order.
  WIDE_SEARCH      — {{ "kind":"WIDE_SEARCH", "target":"diamond_ore" }}
                     Scans BLOCKS and ENTITIES in an expanding cube. The target
                     MUST be a block or mob id. It cannot find a structure:
                     "end_city" is not a block, so the scan runs forever and
                     finds nothing. For structures use LOCATE.
                     Set "extra":{{"radius":N}} to search no further than N
                     blocks. N is a MAXIMUM distance, not a target size: the bot
                     sweeps one cube of that radius and then stops, so radius 4
                     scans only the single 16-block cell it stands in. Omit
                     radius entirely to keep the default expanding search (32,
                     then 64, 128, 256, then 512, where it gives up) — never
                     pass a large N "to be safe", that just overrides the
                     default.
  ME_STORE         — {{ "kind":"ME_STORE", "target":"minecraft:cobblestone", "count":64 }}
                     target "all" stores everything evictable. Uses the worn
                     wireless terminal — works from ANYWHERE, no movement.
  ME_WITHDRAW      — {{ "kind":"ME_WITHDRAW", "target":"minecraft:iron_ingot", "count":32 }}
  VAULT_STORE      — {{ "kind":"VAULT_STORE", "target":"all" }} (or one item id)
  VAULT_WITHDRAW   — {{ "kind":"VAULT_WITHDRAW", "target":"minecraft:bread", "count":8 }}

  SPAWN_DRONES     — {{ "kind":"SPAWN_DRONES", "count":3, "blueprint":"" }}
  DESPAWN_DRONES   — {{ "kind":"DESPAWN_DRONES", "count":1 }}
                     Hive gestation: materialize worker drones at the
                     PLAYER's position, paid from the player's hive FE
                     reservoir (needs a powered Spawn Bay on their board).
                     blueprint (optional) names a saved loadout to equip.
                     Use when ordered to "spawn/summon/raise drones" or
                     "dissolve/dismiss drones". Drones are full bots that
                     accept any directive once gestated.

  SPAWN_GOLEM      — {{ "kind":"SPAWN_GOLEM", "count":1, "design":"" }}
                     design (optional) names a saved golem design from the
                     workbench — its chassis materials, weapon and armor.
                     Forge a hive OFFICER (a modular golem): persistent,
                     expensive (2M FE), and its aura halves the upkeep of
                     nearby drones. Needs a powered Golem Forge flanked by
                     2+ Spawn Bays. DISMISS_GOLEM retires one.

  MOUNT_VEHICLE    — {{ "kind":"MOUNT_VEHICLE", "target":"tank", "extra":{{"seat":"0","role":"driver"}} }}
                     Board a Superb Warfare vehicle: target = a vehicle name/
                     type substring ("tank","lav","m1a2","ah6","boat") or empty
                     for the nearest within radius (default 32). Seat 0 is the
                     driver; role "gunner" takes the first armed passenger
                     seat. Once aboard, COMBAT fights FROM the vehicle (turret
                     aims and fires; a driver closes to weapon range — land,
                     boat and helicopter only; airplanes can be gunned, not
                     flown). Vehicles need FE energy and ammo in their hold —
                     the hive charges them from the owner's reservoir.
                     VEHICLES CANNOT BE FOUND BY WIDE_SEARCH OR LOCATE — they
                     are entities, not blocks or structures. If no vehicle is
                     nearby, use SKILL summon_vehicle (hive units only; the
                     owner's FE reservoir pays; the skill mounts it too). A bot
                     with no hive owner cannot summon — say so instead of
                     searching for one.
  REQUISITION      — {{ "kind":"REQUISITION", "target":"vehicle:lav_150" }} or an item id + count
                     Ask the hive to materialize something for FE and wait for
                     it (vehicle arrives repaired + charged, 3 blocks ahead).
                     Prefer SKILL summon_vehicle, which requisitions AND mounts.
  FUSE_BLOCK       — {{ "kind":"FUSE_BLOCK", "extra":{{"mode":"capacity"}} }} (or "x/y/z", or "role":"generator|storage|reactor")
                     Merge the bot with the energy block it is looking at / that
                     the player marked (M) / at x,y,z. A GENERATOR or REACTOR
                     feeds its output into the owner's hive reservoir (amplified);
                     a STORAGE block adds its capacity to the reservoir cap
                     (mode "capacity", default) or is charged FROM the reservoir
                     (mode "output"). Reactors (Mekanism fission, Draconic) are
                     regulated automatically and kept safe. Hive units only —
                     a bot with no owner can fuse but earns nothing.
  MANAGE_FUSION    — the running fusion directive; do not emit directly. Tune it
                     live with the /bot/<name>/manage_fusion action (rate, mode,
                     output_rate) — e.g. "run the reactor at 80%".
  FUSE_BLOCK (sim) — a HNN Simulation Chamber is also fusable: the unit powers it
                     from the reservoir and harvests its mob loot automatically.
                     "train the model" levels it; "auto-matrix on" spends FE to
                     keep it fed with prediction matrices.
  UNFUSE_BLOCK     — {{ "kind":"UNFUSE_BLOCK" }}  Break the fusion.
  DISMOUNT_VEHICLE — {{ "kind":"DISMOUNT_VEHICLE" }}
  DRIVE_VEHICLE    — {{ "kind":"DRIVE_VEHICLE", "x":<int>, "y":<int>, "z":<int>, "count":120 }}
                     Drive the vehicle you pilot to a point (or "target":
                     "<player or entity>" to follow it). Only from the driver
                     seat; count = max seconds. Land/boat/helicopter only.

  MEDITATE         — {{ "kind":"MEDITATE", "count":10 }}
                     The bot sits and cultivates XP (count = levels to
                     gain, max 100). XP is the bot economy's currency:
                     channeling/conjuring, anchoring upkeep, and terminal
                     provisioning all spend it. When an order says
                     "meditate", or a bot is refused for being broke
                     ("this bot is broke"), MEDITATE is the answer.

  ANCHOR_ON        — {{ "kind":"ANCHOR_ON" }}  ANCHOR_OFF — {{ "kind":"ANCHOR_OFF" }}
                     An anchored bot keeps its surrounding chunks loaded
                     (machines run, the ME grid stays whole) at a cost of
                     XP per hour. Anchor before long stationary tasks away
                     from players; release when leaving.

  For "keep X stocked at N" style requests, tell the player to use the
  Cmd tab's ⏲ Keep button (standing orders are created there) — do NOT
  fake it with a one-shot plan.

INVENTORY TASKS ("store", "clean up", "put away", "organize"):
  - "storage" ALWAYS means the bot's VAULT or the ME NETWORK — it is NEVER
    a place or a dimension. Do NOT emit TELEPORT or GOTO for storage tasks;
    ME_STORE/VAULT_STORE work from wherever the bot stands.
  - Essential items (keep unless told otherwise): equipped armor + weapons,
    tools, food, and the wireless terminal. Everything else is fair game.
  - "I don't care which": prefer ME_STORE when a terminal is worn,
    VAULT_STORE otherwise.
  - NEVER emit DROP for an inventory task unless the order literally says
    drop or discard — vault and ME are recoverable, the ground is not.
  - If the classification would move more than half the inventory and the
    order is ambiguous, ASK_PLAYER first.
  CRAFT_REQUEST    — {{ "kind":"CRAFT_REQUEST", "target":"ae2:quantum_helmet", "count":1 }}
                     Submit an AUTOCRAFTING job to the ME network (needs a
                     linked wireless terminal). The grid's CPUs craft; the
                     products land in NETWORK storage — follow with
                     ME_WITHDRAW if the bot must hold them. Only works for
                     items the network has patterns for; the directive fails
                     honestly with the missing-ingredient list otherwise.
  ASK_PLAYER       — {{ "kind":"ASK_PLAYER", "target":"<your question>" }}
                     Stops and asks the PLAYER. Use when the task is ambiguous,
                     two readings conflict, or you need a decision only the
                     player can make (which material, which location, destroy
                     or keep). The answer arrives in the result text as
                     "player says: ..." — plan the NEXT directives with it.
                     Do not ask what you can observe or decide yourself.
  IDLE             — {{ "kind":"IDLE" }}

SKILL PROPOSAL (fallback — only when NO registered skill above covers the subtask
AND the subtask is a bounded, reusable sequence of the directive kinds listed
above): you MAY synthesize a NEW skill inline instead of hand-expanding it. Emit
exactly ONE directive of kind SKILL whose extra carries a declarative "spec" (an
object, not a string) plus "register": true:
{{
  "directives": [
    {{ "kind": "SKILL", "target": "equip_and_fight", "extra": {{
      "spec": {{ "type": "sequence", "children": [
        {{ "type": "directive", "kind": "EQUIP_ALL" }},
        {{ "type": "directive", "kind": "COMBAT", "target": "minecraft:zombie", "extra": {{ "radius": 16 }} }}
      ] }},
      "register": true
    }} }}
  ]
}}
Constraints: spec leaves MUST use only the directive kinds listed above; a "loop"
node MUST set "max_iterations"; never "skill-ref" the skill to itself. The mod
validates the spec and rejects anything invalid — a rejection is safe, just retry
as raw directives. Propose a new skill ONLY for a reusable pattern; a one-off
subtask is fine as raw directives.
"""


def partition_fleet(model: str, task: str, bots_info: str, bot_names: list) -> dict:
    """Split one fleet order into per-bot assignments. Returns {bot: text};
    a bot may be assigned "skip". Raises on parse failure (caller falls
    back to verbatim fan-out)."""
    sys_prompt = (
        "You are the fleet coordinator for a team of Minecraft bots. Split the "
        "operator's order into ONE short instruction per bot, playing to each "
        "bot's role and holdings. If a bot has nothing useful to do, assign "
        "exactly \"skip\". Reply with ONLY a JSON object mapping every bot "
        "name to its instruction.\n\nThe team:\n" + bots_info
        + "\n\nBot names: " + ", ".join(bot_names))
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                **think_field(),
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": task},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 400},
            },
            timeout=_OLLAMA_TIMEOUT,
        )
    resp.raise_for_status()
    _body = resp.json()
    ensure_not_truncated(_body, "partition_fleet")
    out = json.loads(answer_text(_body) or "{}")
    return {k: str(v) for k, v in out.items() if k in bot_names}


_CLASSIFY_SYSTEM_PROMPT = """You are the front desk for {bot_name}, an AI bot in Minecraft.

An operator just said something to this bot. Decide what they WANT before
anything is executed:

- "task": an instruction to DO something in the world. Ask the bot to move,
  gather, mine, build, craft, fight, follow, stop, explore, or otherwise
  change its position, inventory, or the world. Orders can be phrased as
  questions ("can you get me some wood?" is still a task).
- "chat": a question or remark addressed to the bot itself — asking who or
  what it is, what it thinks, how it is doing, its opinion, a greeting, a
  joke, small talk, or anything answerable without touching the world.

Ambiguous cases resolve to "task" when any world-changing action is implied.

Output ONLY this JSON, no prose, no markdown fences:
{{"kind": "chat" | "task"}}

The operator said: {text}"""


def classify_message(model: str, bot_name: str, text: str) -> str:
    """Decide whether a player message is conversation or an instruction.

    Returns "chat" or "task". Fails to "task" on any error — the safe
    direction: a mistaken order is visible and correctable (the player sees
    the plan), whereas a mistaken chat silently drops a real instruction.

    The answer is one of two short JSON objects ({"kind": "chat"} / {"kind":
    "task"}). The budget below was 24 tokens, which fits the answer and
    NOTHING else: on 2026-11-20 21:23Z a message hit eval_count=24 with
    done_reason=length. Thinking was already off (LLM_THINK defaults false), so
    the 24 went on the reply itself: `format: "json"` constrains the SHAPE of
    the reply, not its length, and a model may restate the question before it
    emits the JSON.

    What hitting the limit did NOT do, established from that trial and from
    the call sites (agent.py:700 and :905) rather than assumed: classify is
    asked only chat-vs-task. A length stop reaches `return "task"` through the
    SAME path as a genuine "task", so it cannot misroute a chat as a task in a
    way that loses the order -- "task" is the fallback direction precisely
    because a mistaken order is visible and correctable. What it costs is the
    other way: an utterance that really was chatter gets planned instead of
    answered. 128 removes the limit as a cause. Whether a longer reply means
    more preamble, and on which model, is NOT established here: the model the
    agent uses is not reachable from this seat without a pod exec, and
    measuring it would mean loading weights on the shared GPU.
    """
    sys_prompt = _CLASSIFY_SYSTEM_PROMPT.format(bot_name=bot_name, text=text)
    try:
        with ollama_lock:
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    **think_field(),
                    "model": model,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": text},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.0, "num_predict": _CLASSIFY_NUM_PREDICT},
                },
                timeout=60,
            )
        resp.raise_for_status()
        _body = resp.json()
        ensure_not_truncated(_body, "classify_message")
        data = json.loads(_strip_codefence(answer_text(_body)))
        kind = str(data.get("kind", "")).strip().lower()
        if kind in ("chat", "task"):
            return kind
        log.warning("[%s] classify returned %r — defaulting to task", bot_name, kind)
    except Exception as e:
        log.warning("[%s] classify failed (%s) — defaulting to task", bot_name, e)
    return "task"


def converse(model: str, bot_name: str, persona: str, text: str,
             world_state: str = "", memory_context: str = "",
             directive_line: str = "", history: list | None = None) -> str:
    """One conversational turn with a bot's L3. No plan, no JSON, no dispatch.

    The other half of the Talk/Order split: L3 is powerful and mostly idle,
    and talking to it should not spawn an orchestrator run. Context carries
    the bot's persona, what it can see, and what it is doing — so 'what do
    you make of the terrain' gets an answer from THIS bot, here, now."""
    sys_prompt = (
        f"You are {bot_name}, an AI bot in Minecraft.\n"
        f"Persona: {persona}\n\n"
        f"Your operator is talking WITH you — this is conversation, not an order. "
        f"Nothing you say here is executed. Answer in character, concretely, in "
        f"1-3 sentences. No JSON, no lists unless asked.\n\n"
        f"What you can observe: {world_state or '(nothing reported)'}\n"
        f"What you are doing: {directive_line or 'standing by'}\n"
        + (f"Relevant memories:\n{memory_context}\n" if memory_context else "")
    )
    # The transcript rides along as real chat turns — without it every
    # reply started the conversation over (player: "the chat is disjointed").
    messages = [{"role": "system", "content": sys_prompt}]
    for line in (history or [])[-10:]:
        who = str(line.get("who", ""))
        messages.append({
            "role": "assistant" if who == bot_name else "user",
            "content": str(line.get("text", ""))[:400],
        })
    messages.append({"role": "user", "content": text})
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                **think_field(),
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 200},
            },
            timeout=60,
        )
    resp.raise_for_status()
    return answer_text(resp.json()).strip()


def call_exec(model: str, plan: Plan, subtask: Subtask,
              world_state_summary: str = "",
              previous_error: str | None = None,
              dimensions: list[str] | None = None) -> tuple[list[dict[str, Any]], str]:
    log.info("[%s] L3 EXEC call — subtask %d/%d", plan.bot, subtask.id, len(plan.subtasks))
    dim_lines = _dim_lines(dimensions)
    sys_prompt = _EXEC_SYSTEM_PROMPT.format(
        bot_name=plan.bot,
        plan_json=json.dumps(_compact_plan(plan), indent=2),
        subtask_json=json.dumps(_compact_subtask(subtask), indent=2),
        world_state=world_state_summary or "(none provided)",
        dimensions=dim_lines,
        skills=_skills_lines(),
        error=previous_error or "(none)",
    )
    user = f"Execute subtask {subtask.id}: {subtask.description}"
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                **think_field(),
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": _EXEC_NUM_PREDICT},
            },
            timeout=_OLLAMA_TIMEOUT,
        )
    resp.raise_for_status()
    _body = resp.json()
    ensure_not_truncated(_body, "call_exec")
    raw = _strip_codefence(answer_text(_body))
    plan_ref = getattr(plan, "created_at", None)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        trajectory_log.log_call(
            phase="exec", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=None,
            world_state_summary=world_state_summary,
            plan_ref=plan_ref, subtask_id=subtask.id,
            parse_error=f"non-JSON: {e}",
        )
        raise ValueError(f"L3 EXEC returned non-JSON: {e}") from e
    directives = data.get("directives")
    if not isinstance(directives, list) or not directives:
        trajectory_log.log_call(
            phase="exec", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=data,
            world_state_summary=world_state_summary,
            plan_ref=plan_ref, subtask_id=subtask.id,
            parse_error="no directives",
        )
        raise ValueError("L3 EXEC returned no directives")
    parsed = [d for d in directives if isinstance(d, dict) and "kind" in d]
    parsed = _collapse_to_skill(parsed)
    call_id = trajectory_log.log_call(
        phase="exec", bot=plan.bot, model=model,
        prompt_system=sys_prompt, prompt_user=user,
        response_raw=raw, parsed=parsed,
        world_state_summary=world_state_summary,
        plan_ref=plan_ref, subtask_id=subtask.id,
    )
    return parsed, call_id


# ── Replan ─────────────────────────────────────────────────────────────────


_REPLAN_SYSTEM_PROMPT = """You are {bot_name}, persona: {persona}.

A subtask in your plan has failed {attempts} times. Revise THIS subtask only.

Full plan: {plan_json}
Failed subtask: {subtask_json}
Most recent error: {error}

Output ONLY a single replacement subtask JSON (no prose, no fences):
{{
  "id": {subtask_id},
  "description": "...",
  "criteria": "..."
}}

Constraints:
- id MUST equal {subtask_id}.
- description and criteria should differ from the failed version.
- You MUST return that one subtask object. There is no error form: a subtask
  that failed is a subtask to replace, not a reason to abandon the plan.
  Change the approach — different tool, different route, smaller first step,
  explicit prerequisites — until it can plausibly succeed.
"""


def call_replan(model: str, plan: Plan, failed_subtask: Subtask) -> Subtask:
    persona = BOT_PERSONAS.get(plan.bot, "generalist")
    log.info("[%s] L3 REPLAN call — subtask %d (attempts=%d)",
             plan.bot, failed_subtask.id, failed_subtask.attempts)
    sys_prompt = _REPLAN_SYSTEM_PROMPT.format(
        bot_name=plan.bot,
        persona=persona,
        plan_json=json.dumps(_compact_plan(plan), indent=2),
        subtask_json=json.dumps(_compact_subtask(failed_subtask), indent=2),
        error=failed_subtask.error or "(unknown)",
        attempts=failed_subtask.attempts,
        subtask_id=failed_subtask.id,
    )
    user = "Revise the failed subtask."
    with ollama_lock:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                **think_field(),
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 384},
            },
            timeout=_OLLAMA_TIMEOUT,
        )
    resp.raise_for_status()
    _body = resp.json()
    ensure_not_truncated(_body, "call_replan")
    raw = _strip_codefence(answer_text(_body))
    plan_ref = getattr(plan, "created_at", None)
    sid = failed_subtask.id
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        trajectory_log.log_call(
            phase="replan", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=None,
            plan_ref=plan_ref, subtask_id=sid,
            parse_error=f"non-JSON: {e}",
        )
        raise PlanValidationError(f"replan returned non-JSON: {e}") from e
    if isinstance(data, dict) and data.get("error"):
        trajectory_log.log_call(
            phase="replan", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=data,
            plan_ref=plan_ref, subtask_id=sid,
            parse_error=f"refused: {data.get('error')}",
        )
        raise PlanValidationError(f"L3 refused replan: {data.get('error')}")
    validate_subtask_dict(data)
    if data["id"] != failed_subtask.id:
        trajectory_log.log_call(
            phase="replan", bot=plan.bot, model=model,
            prompt_system=sys_prompt, prompt_user=user,
            response_raw=raw, parsed=data,
            plan_ref=plan_ref, subtask_id=sid,
            parse_error=f"id mismatch: got {data['id']}, expected {failed_subtask.id}",
        )
        raise PlanValidationError(f"replan returned id {data['id']}, expected {failed_subtask.id}")
    trajectory_log.log_call(
        phase="replan", bot=plan.bot, model=model,
        prompt_system=sys_prompt, prompt_user=user,
        response_raw=raw, parsed=data,
        plan_ref=plan_ref, subtask_id=sid,
    )
    return Subtask.from_dict({
        **data, "status": "pending", "attempts": 0,
        "directives": [], "error": None,
    })


_REFINE_SKILL_PROMPT = """You are {bot_name}, an AI bot in Minecraft.

You proposed a NEW declarative skill (a SKILL directive carrying an inline
"spec"), but the mod's deterministic validator REJECTED it. Fix ONLY the spec
so it validates. Do not change the skill's intent.

Rejected spec (JSON):
{spec_json}

Validator error:
{error}

Correct SkillSpec contract (a single JSON object):
{{
  "id": "<skill_id>",
  "nodes": {{ <one root node> }}
}}

Node grammar (type → required fields):
  "sequence" / "fallback" → "children": [node, ...]
  "loop" → "body": node, "max_iterations": N (N must be > 0), optional "while"
  "if" → "condition": str, "then": node, optional "else": node
  "skill" (reference an existing skill) → "ref": "<skill_id>"
  "directive" (leaf) → "kind": one of {valid_kinds}, optional
      "target"/"count"/"radius"/"x"/"y"/"z"/"extra" (all strings)

Rules the validator enforces:
  - a "loop" MUST set max_iterations > 0 (never 0 or missing)
  - a "directive" leaf MUST set a valid "kind"
  - never reference the skill itself ("skill" with ref == its own id)
  - any "${{name}}" in nodes must be declared in the top-level "params" map

Output ONLY the corrected spec as a JSON object (no prose, no fences), or:
{{"error": "<why it cannot be fixed>"}}
"""


def refine_skill(model: str, bot_name: str, spec: str, error: str) -> dict | None:
    """Feed a validator rejection back to L3 to fix an inline skill spec.

    Returns the corrected spec dict (with "id" + "nodes"), or None if L3
    gives up or returns non-JSON. The caller re-wraps via _repair_directive.
    """
    sys_prompt = _REFINE_SKILL_PROMPT.format(
        bot_name=bot_name,
        spec_json=spec,
        error=error,
        valid_kinds=", ".join(sorted(_VALID_DIRECTIVE_KINDS)),
    )
    user = "Fix the rejected skill spec."
    log.info("[%s] L3 REFINE-SKILL call — error: %s", bot_name, error[:120])
    try:
        with ollama_lock:
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    **think_field(),
                    "model": model,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2, "num_predict": 768},
                },
                timeout=_OLLAMA_TIMEOUT,
            )
        resp.raise_for_status()
    except Exception as e:
        log.warning("[%s] refine_skill call failed: %s", bot_name, e)
        return None
    _body = resp.json()
    ensure_not_truncated(_body, "refine_skill")
    raw = _strip_codefence(answer_text(_body))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("[%s] refine_skill returned non-JSON: %s", bot_name, e)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error") and "id" not in data:
        log.info("[%s] L3 gave up on skill spec: %s", bot_name, data.get("error"))
        return None
    return data


# ── helpers ────────────────────────────────────────────────────────────────


def _compact_plan(plan: Plan) -> dict[str, Any]:
    """Prompt-sized plan outline. Full to_dict() re-embeds every subtask's
    emitted directives on every EXEC call — pure token bloat. L3 only needs
    the shape of the plan for context."""
    return {
        "task": plan.task,
        "bot": plan.bot,
        "current_subtask_id": plan.current_subtask_id,
        "subtasks": [
            {"id": s.id, "status": s.status, "description": s.description}
            for s in plan.subtasks
        ],
    }


def _compact_subtask(subtask: Subtask) -> dict[str, Any]:
    """Current subtask in full, but cap previously-emitted directives to the
    last 2 (enough for retry context, not the whole history)."""
    d = subtask.to_dict()
    dirs = d.get("directives") or []
    if len(dirs) > 2:
        d["directives"] = dirs[-2:]
    return d


def _strip_codefence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


_PREVIEW_CHARS = 600
_TAIL_CHARS = 200

# The SCRIPT call's token budget, kept apart from every other call's. A script
# is a whole program rather than a short answer: at the plan's 1024 tokens a
# correct script hit the limit mid-block on 2026-11-20 19:10Z (thinking was off,
# so the budget was all content) and the unclosed fence read as "no block".
# 6144 fits inside the call timeout: at 32-37 tok/s that is ~166-192 s of
# decode plus a <=68 s cold load, under 420 s. The window is not a constraint
# (OLLAMA_CONTEXT_LENGTH=114688 holds prompt + reply), so this is the cap.
# Changing this MUST NOT change any other call's num_predict.
_SCRIPT_NUM_PREDICT = 6144

# The classify call's budget. The answer is ~20 characters of JSON, but a model
# served at temperature 0 can still spend tokens restating the question before
# it emits them, and `format: "json"` constrains the SHAPE of the reply, not
# its length. 24 was enough for a terse reply and no more: on 2026-11-20
# 21:23Z classification hit eval_count=24 with done_reason=length. 128 leaves
# room for a short preamble while staying far below anything that could cost
# latency on a call made once per inbound message.
_CLASSIFY_NUM_PREDICT = 128

# The PLAN call's budget. Measured on the deployment (test gateway, model
# qwen3.8:27b-q4_K_M, the real _PLAN_SYSTEM_PROMPT, 2026-11-20 ~22:2xZ), six
# real one-shot goals at the old 1024:
#
#   done=stop  eval 995   thinking 3262  content 442
#   done=stop  eval 805   thinking 2593  content 449
#   done=LENGTH eval 1024 thinking 4037  content 0     <- no reply at all
#   done=LENGTH eval 1024 thinking 4108  content 0     <- no reply at all
#   done=LENGTH eval 1024 thinking 3978  content 0     <- no reply at all
#   done=stop  eval 870   thinking 3059  content 284
#
# So four in six failed, and the budget was NOT going on the plan: a plan is
# 284-879 chars, while 2600-4100 chars of THINKING preceded it. `think: false`
# is sent by think_field() and the gateway forwards it (app/main.py:319), yet
# this model still emits thinking for the plan prompt; that is measured, not
# explained, and is out of scope for this fix.
#
# Across all nine calls measured, the thinking block ran 2093-8482 chars: a 4x
# swing with nothing in this code controlling it. That is a budget for thinking
# we cannot see, not slack for a longer plan.
#
# At 4096 the same goals stopped at eval 1040, 2396 (thinking 3515, 8482) with
# the plan intact. 4096 is four times the largest plan seen, clears the largest
# eval_count measured (2396), and matches the ceiling of what thinking has been
# observed to spend. Decode at 32-37 tok/s puts the worst case near 120 s,
# inside the call timeout; the value also stays well inside the SCRIPT call's
# 6144 footprint.
#
# This constant is the PLAN call's only. The SCRIPT call has its own
# (_SCRIPT_NUM_PREDICT); a shared figure would be a coincidence, not a budget.
_PLAN_NUM_PREDICT = 4096

# The L3 EXEC call's token budget, extracted from a literal 768 with the value
# UNCHANGED. On the 2026-11-21 21:55Z rerun both Axiom and Forge logged
# "subtask 1 exec failed: model hit the token limit (done_reason=length,
# eval_count=768)", so 768 is a real ceiling that this call actually reaches --
# but how much room a correct reply needs is NOT measured yet.
# unmeasured, sized later: the lead measures eval_count on test after deploy
# and the number is set from that. Do not guess a larger value here.
# This is the EXEC call's only; it does not move any other call's budget.
_EXEC_NUM_PREDICT = 768


def preview_reply(raw: str) -> str:
    """A bounded, newline-escaped preview of a model reply for the log.

    Model output only: never the prompt, never headers. This exists because a
    parse failure or a missing fence is unactionable from a message like "line
    9 column 5" — the next reader needs to see the shape of what actually came
    back (a think tag, prose before the fence, a trailing comma) without the
    whole reply, which can be many KiB of JavaScript. Newlines are escaped so
    one line of log decodes back to the same bytes.
    """
    if raw is None:
        return "<no reply>"
    return repr(raw[:_PREVIEW_CHARS]) + (
        f"... [+{len(raw) - _PREVIEW_CHARS} chars]" if len(raw) > _PREVIEW_CHARS else "")


def tail_reply(raw: str, n: int = _TAIL_CHARS) -> str:
    """The last `n` chars of a reply, escaped, for diagnosing a missing fence.

    A head-only preview cannot distinguish "no closing fence at all" from "the
    fence is there but the block is empty" from "prose follows the fence" --
    all three look identical in the first 600 chars, and they need three
    different fixes. Model output only, same escape rule as preview_reply.
    """
    if raw is None:
        return "<no reply>"
    if len(raw) <= n:
        return repr(raw)
    return f"[+{len(raw) - n} chars]..." + repr(raw[-n:])


# G-4: ONE definition of what a closing fence is, shared by the extractor and
# the diagnosis. They had drifted apart -- the extractor accepted any ``` after
# an optional newline, while the diagnosis required a bare fence alone on its
# line -- so a reply could be reported "unusable" by the diagnosis and yet be
# extracted, or the reverse. Two answers to one question is how a warning ends
# up naming a cause the extractor never acted on.
#
# An OPENING token: ``` plus a language tag, ending its line -- a tag is a whole
# word, so "```js that's it" is not an opening fence for js.
_OPEN_FENCE_RE = re.compile(r"```([A-Za-z0-9_+.-]+)[ \t]*\r?(?=\n|$)")
# A bare ``` that CLOSES an open js block.
#
# Two constraints pull against each other, and both are real replies:
#   - a model that finishes a good block then explains itself on the same line
#     ("... ``` that's the script") is handing us the script; the pre-da97977
#     regex took it, and refusing it throws away a whole correct program.
#   - a ``` inside the script's own text ("const s = '```';") is not a fence;
#     treating it as one returns a truncated program that still binds.
# What separates them is which quote it sits in: a fence immediately inside a
# ' or " or ` that is still open belongs to the script. Scanning for the first
# bare fence NOT inside an open string is a cheap stand-in for that, and it is
# what the old lazy regex approximated by taking the first ``` anywhere.
_CLOSE_FENCE_RE = re.compile(r"```")
_JS_TAGS = ("js", "javascript")


def _find_close(text: str, start: int) -> int:
    """Index of the bare fence that closes an open js block, or -1.

    Walks from `start` tracking whether a ' " or ` has been left open on the
    fence's own line, so a ``` inside a string in the script is skipped. A
    fence at the start of a line, or after only whitespace, always closes.
    """
    pos = start
    quote = ""
    while pos < len(text):
        m = _CLOSE_FENCE_RE.search(text, pos)
        if m is None:
            return -1
        # A tagged fence is a new opening, never a closer: "```js" while a js
        # block is open is the model starting another block, not ending this.
        if text[m.end():m.end() + 1].isalnum() or text[m.end():m.end() + 1] == "_":
            pos = m.end()
            continue
        # Recompute the quote state from the start of this line up to the fence;
        # scripts are short and this keeps the two rules independent.
        line_start = text.rfind("\n", 0, m.start()) + 1
        prefix = text[line_start:m.start()]
        q = ""
        i = 0
        while i < len(prefix):
            ch = prefix[i]
            if ch == "\\" and q:
                i += 2
                continue
            if q:
                if ch == q:
                    q = ""
            elif ch in "'\"`":
                q = ch
            i += 1
        if not q:
            return m.start()
        pos = m.end()
    return -1


def _scan_fence_blocks(text: str):
    """Yield (opens_js, closes_js, body) as each js block closes.

    The walk is left to right with an inside flag: a tagged fence opens only
    when the tag is js/javascript and nothing is open, a bare fence closes only
    when a js block is open, anything else is ignored. Counting opens and
    closes independently cannot answer the question -- a python block's closer
    is a bare fence, so a tally counts it as a js close and hides a genuinely
    missing one (python+python+unclosed js once read "opened 1, closed 2").

    A closing fence may be followed by prose on its own line: the script is
    complete at the fence, and what the model says after it is not part of it.
    A bare ``` inside an open js block always closes; that is the same rule the
    pre-da97977 regex used, and it means a template literal containing a fence
    ends the block early. Callers get the bytes up to the fence, exactly as the
    old extractor did.

    Yields nothing for a block that never closes; those contribute counts only.
    Use _fence_census when only the counts are needed.
    """
    opens_js = closes_js = 0
    inside_js = False
    open_start = 0
    pos = 0
    while pos < len(text):
        if inside_js:
            close_at = _find_close(text, pos)
            if close_at < 0:
                break
            closes_js += 1
            inside_js = False
            yield opens_js, closes_js, text[open_start:close_at]
            pos = close_at + 3
        else:
            m = _OPEN_FENCE_RE.search(text, pos)
            if m is None:
                break
            if m.group(1).lower() in _JS_TAGS:
                opens_js += 1
                inside_js = True
                # The body starts after the fence's own line terminator, so the
                # newline that ends the ```js line is not part of the script.
                open_start = m.end()
                if text.startswith("\r\n", open_start):
                    open_start += 2
                elif text.startswith("\n", open_start):
                    open_start += 1
            pos = m.end()


def _fence_census(text: str) -> tuple[int, int, bool]:
    """(opens_js, closes_js, still_open) using the same walk as extraction."""
    opens_js = closes_js = 0
    inside_js = False
    pos = 0
    while pos < len(text):
        if inside_js:
            close_at = _find_close(text, pos)
            if close_at < 0:
                break
            closes_js += 1
            inside_js = False
            pos = close_at + 3
        else:
            m = _OPEN_FENCE_RE.search(text, pos)
            if m is None:
                break
            if m.group(1).lower() in _JS_TAGS:
                opens_js += 1
                inside_js = True
            pos = m.end()
    return opens_js, closes_js, inside_js


def fence_diagnosis(raw: str) -> str:
    """Name why extract_script_block found no block, for the warning line.

    Kept separate from the extractor so the extractor stays a pure parser: this
    only ever describes a reply that already failed, and never decides anything.
    """
    opens_js, closes_js, still_open = _fence_census(raw or "")
    if opens_js == 0:
        return "no-js-fence (```js/```javascript not found)"
    if still_open or closes_js < opens_js:
        return f"missing-closing-fence (opened {opens_js}, closed {closes_js})"
    return f"fence-present-but-block-unusable (opened {opens_js}, closed {closes_js})"


def extract_script_block(model_text: str) -> str | None:
    """Pull a planner-authored script out of its own reply.

    The script is asked for in a SECOND call, never in the plan call. That
    keeps `format: json` on the plan (so the common step-list path is unchanged
    and still held to JSON by the model itself), and it means a script that is
    malformed costs the script and nothing else: the plan from the first call
    is already parsed before this ever runs.

    Why not one call: `build_dpo_dataset.py` builds its chosen/rejected pairs
    from `response_raw` verbatim. A script sharing the plan's reply would reach
    the trainer through `parsed` and again through the field it trains on, and
    a script inside the JSON string makes a 27B model responsible for escaping
    arbitrary JavaScript — on test at 2026-11-20 15:57Z it emitted one raw
    0x0a inside the string and the whole plan was lost. Two calls make both
    problems unrepresentable rather than merely handled.

    Returns the script source, or None when the reply carries no usable block.
    None means "no script": the goal runs its steps and nothing is bound.
    """
    text = model_text or ""
    if not isinstance(text, str):
        return None
    # The same walk fence_diagnosis reports on: one definition of what closes
    # a js block, so the warning can never name a cause this did not act on.
    for _, _, body in _scan_fence_blocks(text):
        # The newline that separates the closing fence from the code is not
        # part of the script; the old regex swallowed it with `\n?` before the
        # fence. Stripping keeps the extracted source byte-identical to what
        # shipped before this refactor, so nothing downstream sees a new blank
        # line at the end of every script.
        script = body.strip("\r\n")
        return script if script.strip() else None
    return None


def render_script_system_prompt(bot_name: str, persona: str, skills: str | None = None) -> str:
    """The L3 script prompt as the model receives it.

    The one renderer for this prompt: call_script uses it, and so do the tests,
    so a test cannot re-encode the render and miss a defect in it (reviewer
    F-1, 2026-11-21: rendering through the same bug kept a doubled-brace
    regression green). The script surface carries plain single braces and is
    spliced in as a value, never through .format.
    """
    # The same gate as the planner prompt, for the same bot. The two surfaces
    # MUST agree: offering scripts in one and not the other would let a bot
    # that was never offered a script reach the L3 call for one.
    _offered, _why = script_mode(bot_name)
    return _SCRIPT_SYSTEM_PROMPT.format(
        bot_name=bot_name, persona=persona,
        skills=_skills_lines() if skills is None else skills,
        script_surface=_SCRIPT_SURFACE if _offered else "")


def call_script(
    bot_name: str,
    task: str,
    plan: dict | None = None,
    model: str = "",
    world_state_summary: str = "",
) -> str | None:
    """Ask the planner for the script alone, in a non-JSON call.

    Only called when the plan call set `wants_script`. Everything this returns
    is dry-gated before it can be bound, so a bad script is refused rather than
    run. A failure here is not a goal failure: it yields None and the goal
    proceeds on the plan's steps.
    """
    persona = BOT_PERSONAS.get(bot_name, "generalist")
    log.info("[%s] L3 SCRIPT call — task: %s", bot_name, task[:60])
    sys_prompt = render_script_system_prompt(bot_name, persona)
    user = json.dumps({
        "task": task,
        "plan": plan,
        "world_state": world_state_summary,
    }, ensure_ascii=False)
    try:
        with ollama_lock:
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    **think_field(),
                    "model": model,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    # NOT JSON mode: the reply is one fenced JavaScript block.
                    # Its own budget, larger than the plan's: a script is a
                    # whole program, and at 1024 a correct answer ran out of
                    # tokens mid-block (2026-11-20 19:10Z trial, thinking off,
                    # done_reason=length, eval_count=1024) leaving the fence
                    # unclosed. The plan and other calls keep their budgets.
                    "options": {"temperature": 0.2,
                                "num_predict": _SCRIPT_NUM_PREDICT},
                },
                timeout=_OLLAMA_TIMEOUT,
            )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as e:
        # ValueError covers a body that is not JSON.
        log.warning("[%s] L3 SCRIPT call failed: %s", bot_name, e)
        return None
    try:
        # answer_text raises TruncatedAnswer, so it belongs inside the guard:
        # that exception is the whole reason this block exists.
        raw = answer_text(body)
        # G-3: a length-stop is no-script even when content came back. The
        # guard in answer_text fires only on EMPTY content, so a reply cut
        # mid-block arrives here holding a partial fence -- and if the cut
        # happens to land after a closing fence, extraction hands back a
        # program that is half what the model meant and looks well-formed.
        # Truncation is therefore decided before extraction, on the reply's
        # own report of why it stopped, never on what survived.
        if body.get("done_reason") == "length":
            raise TruncatedAnswer(
                "model stopped for length after %d chars (eval_count=%s); a "
                "partial script is never bound"
                % (len(raw), body.get("eval_count")))
        script = extract_script_block(raw)
    except TruncatedAnswer as e:
        # The model hit its budget mid-script. A truncated script would compile
        # to something that is not what it meant, so treat it as no script and
        # let the goal run its plan rather than bind a half-written program.
        log.warning("[%s] L3 SCRIPT call truncated: %s", bot_name, e)
        return None
    if script is None:
        # The first trial's warning showed a real script that this rejected, and
        # a head-only preview could not say why: every candidate cause (no close,
        # empty block, trailing prose) looks the same in the first 600 chars.
        # So log the shape AND the tail, plus what the backend said about the
        # reply -- if done_reason were 'length' the file would be cut, which is a
        # different bug from a fence the model failed to close.
        log.warning(
            "[%s] L3 SCRIPT call returned no block; %s; done_reason=%r eval_count=%r "
            "len(content)=%d; head: %s; tail: %s",
            bot_name, fence_diagnosis(raw), body.get("done_reason"),
            body.get("eval_count"), len(raw), preview_reply(raw), tail_reply(raw))
    return script
