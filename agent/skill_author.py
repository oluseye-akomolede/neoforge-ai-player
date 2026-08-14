"""Off-loop skill author (v10 Phase 2, role-separated).

Separation of concerns: L3 (local qwen2.5) stays in the live loop — it plans and
dispatches. Authoring new reusable skills is a *judgment* task L3 is too small to
do reliably (it greedily seed-matches on one verb and drops the rest of a
two-step task), so it moves OFF-LOOP to a stronger model (DeepSeek), fed by the
append-only trajectory log.

Pipeline (one pass, ~90s cadence, no bot interaction):

  1. mine  — read trajectory JSONL, reconstruct each *completed* plan's directive
             sequence (flattened across its subtasks, in order), keep the ones
             that are 2-4 raw, reusable, non-skill directives.
  2. propose — send the batch to DeepSeek to generalize into parameterized
             SkillSpec JSON (id / description / params / nodes).
  3. register — POST each spec to the mod's /skills (POST) endpoint, which
             validates + stores server-globally WITHOUT executing it (the mod
             endpoint never touches a bot's directive slot).

A local signature-based state file prevents re-proposing the same routine every
pass. Everything is best-effort: a DeepSeek outage or a full disk must never
break the bot.
"""
from __future__ import annotations

import json
import logging
import pathlib
import threading
import time

import requests

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_URL,
    SKILL_AUTHOR_ENABLED,
    SKILL_AUTHOR_INTERVAL,
)
import trajectory_log

# Reuse the authoritative kind lists + fence stripper from the planner (single
# source of truth), not local copies that can drift as directive kinds are added.
from l3_planner import _VALID_DIRECTIVE_KINDS, _NON_REUSABLE_KINDS, _strip_codefence

log = logging.getLogger("aibot.skill_author")

# A routine is "authorable" at 2-4 raw directives; the deterministic in-loop
# shim already handles 2-3 within a single EXEC, so the author's real win is the
# cross-subtask sequences the shim never sees (L3 splits them before EXEC).
_MIN_ROUTINE_LEN = 2
_MAX_ROUTINE_LEN = 4
_MAX_ROUTINES_PER_PASS = 8

_STATE_FILE = trajectory_log.DIR / "skill_author_state.json"


def _deepseek_chat(messages: list[dict], *, model: str | None = None,
                   temperature: float = 0.2, max_tokens: int = 2048) -> str:
    """One OpenAI-compatible chat completion against DeepSeek. Raises on failure
    (the caller is best-effort and will catch)."""
    r = requests.post(
        f"{DEEPSEEK_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model or DEEPSEEK_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        },
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"DeepSeek returned no choices: {data}")
    return choices[0]["message"]["content"] or ""


# ── trajectory mining ───────────────────────────────────────────────────────

def _signature(directives: list[dict]) -> str:
    """Ordered kind signature, e.g. "CRAFT>STORE_ALL"."""
    return ">".join(str(d.get("kind", "")).upper() for d in directives)


def _is_authorable(directives: list[dict]) -> bool:
    if not (_MIN_ROUTINE_LEN <= len(directives) <= _MAX_ROUTINE_LEN):
        return False
    for d in directives:
        kind = str(d.get("kind", "")).upper()
        if kind == "SKILL" or kind not in _VALID_DIRECTIVE_KINDS or kind in _NON_REUSABLE_KINDS:
            return False
    return True


def _leaf(d: dict) -> dict:
    """A directive reduced to its skill-authoring-relevant fields (numeric
    fields stringified, matching the leaf contract the mod expects)."""
    node = {"kind": str(d.get("kind", "")).upper()}
    for field in ("target", "count", "radius", "x", "y", "z"):
        v = d.get(field)
        if v is not None and str(v) != "":
            node[field] = str(v)
    extra = d.get("extra")
    if isinstance(extra, dict) and extra:
        node["extra"] = {k: str(v) for k, v in extra.items()}
    return node


def mine_trajectories(limit: int = _MAX_ROUTINES_PER_PASS) -> list[dict]:
    """Reconstruct completed plans' raw directive sequences from the trajectory
    log. Returns a list of {"task", "signature", "sequence"} for authorable
    routines, deduped by kind signature. Best-effort: returns [] on any error."""
    routines: dict[str, dict] = {}
    closed = {}  # plan_ref -> task (only status "complete")
    execs: dict[str, list[dict]] = {}  # plan_ref -> (subtask_id, parsed)

    try:
        trajectory_log.DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(trajectory_log.DIR.glob("trajectory-*.jsonl"))
        for fp in files:
            try:
                with open(fp, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("type") == "plan_close":
                            if rec.get("status") == "complete" and rec.get("plan_ref"):
                                closed[rec["plan_ref"]] = rec.get("task", "")
                        elif rec.get("type") == "call" and rec.get("phase") == "exec":
                            pr = rec.get("plan_ref")
                            parsed = rec.get("parsed")
                            if pr and isinstance(parsed, list):
                                execs.setdefault(pr, []).append(
                                    (rec.get("subtask_id") or 0, parsed))
            except OSError:
                continue
    except Exception as e:  # noqa: BLE001 — best-effort by design
        log.exception("trajectory mining failed (non-fatal)")
        print(f"[skill-author] mining error: {e}")
        return []

    for plan_ref, task in closed.items():
        items = execs.get(plan_ref)
        if not items:
            continue
        items.sort(key=lambda t: t[0])
        flat: list[dict] = []
        for _, parsed in items:
            flat.extend(p for p in parsed if isinstance(p, dict) and "kind" in p)
        if not _is_authorable(flat):
            continue
        sig = _signature(flat)
        if sig in routines:
            continue
        routines[sig] = {
            "task": task,
            "signature": sig,
            "sequence": [_leaf(d) for d in flat],
        }
        if len(routines) >= limit:
            break

    return list(routines.values())


# ── state ───────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    try:
        trajectory_log.DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        log.exception("skill-author state save failed (non-fatal)")


# ── proposal ────────────────────────────────────────────────────────────────

_NODE_TYPE_ALIASES = {
    "sequence": "sequence", "fallback": "fallback", "loop": "loop", "if": "if",
    "skill": "skill", "skill_ref": "skill", "ref": "skill",
    "directive": "directive", "action": "directive",
}


def _normalize_node(node):
    """Repair DeepSeek's two most common node-tree mistakes deterministically:
    (1) writing the node type as the map KEY instead of a "type" field
        ({"sequence": {...}} -> {"type": "sequence", ...}), and (2) omitting
        "type": "directive" on a leaf that carries a "kind". Mirrors the mod's
        exact SkillNode contract so a proposal validates first try. Recursive."""
    if not isinstance(node, dict):
        return node
    if "type" not in node:
        for k, t in _NODE_TYPE_ALIASES.items():
            if k in node:
                body = node[k]
                if isinstance(body, dict):
                    node = {"type": t, **{kk: vv for kk, vv in body.items() if kk != k}}
                else:
                    node = {"type": t, ("ref" if t == "skill" else "kind"): str(body)}
                break
    if "type" not in node and "kind" in node:
        node = {"type": "directive", **node}
    if isinstance(node.get("children"), list):
        node["children"] = [_normalize_node(c) for c in node["children"]]
    for k in ("body", "then", "else"):
        if isinstance(node.get(k), dict):
            node[k] = _normalize_node(node[k])
    return node


def _normalize_spec(spec: dict) -> dict:
    """Normalize a proposed SkillSpec: repair the nodes tree + coerce params
    values to strings (SkillSpec.parse reads them via getAsString)."""
    if not isinstance(spec, dict):
        return spec
    if isinstance(spec.get("nodes"), dict):
        spec["nodes"] = _normalize_node(spec["nodes"])
    params = spec.get("params")
    if isinstance(params, dict):
        spec["params"] = {str(k): str(v) for k, v in params.items()}
    return spec


_PROPOSE_SYSTEM = """You are the skill author for a fleet of AI Minecraft bots.

The fleet's local planner (a small model) decomposes a task into directives but
fails at *authoring*: it greedily matches one verb to an existing skill and drops
the rest of a two-step task. Your job is to author NEW reusable skills from the
bot's own successful trajectories, so the planner can match a whole routine
instead of half of one.

Given (a) the currently registered skills and (b) a batch of *routines* the bots
actually ran (a task plus the ordered directive sequence they executed to
complete it), propose parameterized skills that generalize them.

Rules:
  - Propose ONLY skills that are genuinely NEW — do NOT duplicate or overlap an
    existing skill below, and do NOT restate a seed under a new name.
  - Generalize across the routines: if two routines differ only in a target item
    or a count, that is ONE parameterized skill, not two.
  - Every skill is a single JSON object in the SkillSpec contract:
      {"id": "...", "description": "...", "params": {"name": "type"},
       "nodes": {"<one root node>"}}
    optional: "verify" (a post-run predicate), "produces" (terminal item id).
  - Node grammar — EVERY node is a JSON object with a literal "type" field
    (never use the node type as a JSON key):
      "sequence" / "fallback" -> "children": [node, ...]
      "loop" -> "body": node, "max_iterations": N (N > 0), optional "while"
      "if" -> "condition": str, "then": node, optional "else": node
      "skill" (reference an existing skill) -> "ref": "<skill_id>"
      "directive" (leaf) -> "kind": one of the __VALID_KINDS__, optional
          "target"/"count"/"radius"/"x"/"y"/"z"/"extra" (all strings)
  - Concrete example (a two-step craft-then-store skill):
      {"id": "craft_and_store", "description": "Craft N of an item, then store.",
       "params": {"item": "item_id", "count": "int"},
       "nodes": {"type": "sequence", "children": [
         {"type": "directive", "kind": "CRAFT", "target": "${item}", "count": "${count}"},
         {"type": "directive", "kind": "STORE_ALL"}
       ]}}
  - A "directive" leaf MUST set a valid "kind". A "loop" MUST set
    max_iterations > 0. Never reference the skill itself.
  - Any "${name}" in nodes MUST be declared in the top-level "params" map.
  - Keep every leaf's directive kind within VALID_KINDS below. Prefer flat
    "sequence" trees over deep nesting; do not invent loops or branches the
    routine does not actually need.

Output ONLY a JSON object of this exact shape (no prose, no fences):
  {"skills": [ {SkillSpec...}, ... ]}
Return {"skills": []} if nothing is worth proposing."""


def _valid_kinds_line() -> str:
    return ", ".join(sorted(_VALID_DIRECTIVE_KINDS))


def propose_skills(routines: list[dict], existing_skills: list[dict]) -> list[dict]:
    """Send a batch of mined routines to DeepSeek; return the proposed SkillSpec
    dicts ([] on no proposals or any failure). Best-effort."""
    if not routines or not DEEPSEEK_API_KEY:
        return []

    existing = [{"id": s.get("id"), "description": s.get("description")}
                for s in existing_skills if s.get("id")]
    user_payload = {
        "registered_skills": existing,
        "routines": routines,
    }
    user = ("Propose new skills from these trajectories.\n\n"
            + json.dumps(user_payload, indent=2))

    try:
        raw = _deepseek_chat([
            {"role": "system",
             "content": _PROPOSE_SYSTEM.replace("__VALID_KINDS__", _valid_kinds_line())},
            {"role": "user", "content": user},
        ])
    except Exception as e:  # noqa: BLE001
        log.exception("DeepSeek proposal failed (non-fatal)")
        print(f"[skill-author] DeepSeek error: {e}")
        return []

    text = _strip_codefence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[skill-author] DeepSeek returned non-JSON: {e}")
        return []

    skills = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(skills, list):
        return []
    out = []
    for s in skills:
        if isinstance(s, dict) and "id" in s and "nodes" in s:
            out.append(_normalize_spec(s))
    return out


# ── registration ────────────────────────────────────────────────────────────

def _register_spec(spec: dict) -> tuple[str, str]:
    """POST one proposed spec to the mod's /skills (POST). Returns (status, id/error)."""
    from api import register_skill
    try:
        r = register_skill(json.dumps(spec))
    except Exception as e:  # noqa: BLE001
        return "error", str(e)[:120]
    if isinstance(r, dict):
        return r.get("status", "error"), (r.get("id") or r.get("error") or "")[:120]
    return "error", str(r)[:120]


def _run_once() -> dict:
    """One authoring pass: mine -> propose -> register. Returns a summary dict
    (also used by the standalone test). Never raises."""
    from api import skills as api_skills
    summary = {"mined": 0, "proposed": 0, "registered": 0, "rejected": 0, "error": 0}
    if not DEEPSEEK_API_KEY:
        return summary

    routines = mine_trajectories()
    summary["mined"] = len(routines)
    if not routines:
        return summary

    state = _load_state()
    seen = state.setdefault("seen", {})
    fresh = [r for r in routines if r["signature"] not in seen]
    if not fresh:
        return summary

    try:
        existing = (api_skills() or {}).get("skills", [])
    except Exception:
        existing = []

    proposed = propose_skills(fresh, existing)
    summary["proposed"] = len(proposed)

    for spec in proposed:
        sig = None
        status, detail = _register_spec(spec)
        if status == "registered":
            summary["registered"] += 1
            print(f"[skill-author] registered {detail}")
        elif status == "rejected":
            summary["rejected"] += 1
            print(f"[skill-author] rejected {spec.get('id')}: {detail}")
        else:
            summary["error"] += 1
            print(f"[skill-author] register error: {detail}")

    # Mark every freshly-considered routine seen so we don't re-propose it next
    # pass, regardless of outcome. A rejected/empty proposal is still terminal.
    for r in fresh:
        seen[r["signature"]] = {"task": r["task"], "kinds": r["signature"]}
    _save_state(state)
    return summary


def run_forever() -> None:
    """Background worker: author skills off-loop on a fixed cadence."""
    print(f"[skill-author] started (model={DEEPSEEK_MODEL}, interval={SKILL_AUTHOR_INTERVAL}s)")
    while True:
        time.sleep(SKILL_AUTHOR_INTERVAL)
        try:
            summary = _run_once()
            if summary["mined"] or summary["registered"] or summary["rejected"]:
                print(f"[skill-author] pass: {summary}")
        except Exception as e:  # noqa: BLE001 — a bad pass must never kill the worker
            print(f"[skill-author] pass error: {e}")


def start_worker() -> None:
    """Spawn the authoring thread if enabled + keyed. No-op otherwise."""
    if not SKILL_AUTHOR_ENABLED:
        print("[skill-author] disabled (SKILL_AUTHOR_ENABLED != true)")
        return
    if not DEEPSEEK_API_KEY:
        print("[skill-author] disabled (no DEEPSEEK_API_KEY / ANTHROPIC_AUTH_TOKEN)")
        return
    threading.Thread(target=run_forever, name="skill-author", daemon=True).start()
