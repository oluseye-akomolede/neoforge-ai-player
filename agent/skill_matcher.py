"""Deterministic plan-time skill matcher.

Closes the "14b splits a skill-covered task at PLAN" gap: match task text to a
registered seed skill in CODE (no LLM), so a skill-covered task becomes one
SKILL directive and skips L3 decomposition entirely.

This is the plan-time sibling of l3_planner._collapse_to_skill (the exec-time
backstop). Both route to the same five seed skills and the same param names
(l3_planner._SEED_SKILLS). The difference is direction: that one re-routes an
LLM's raw-directive sequence AFTER it decomposed; this one never lets the LLM
decompose at all.

Deliberately conservative — a wrong skill costs more than a slow plan:
  - A rule fires only on an UNMISTAKABLE phrase shape (verb + object + the
    skill's required params).
  - Item ids resolve against the live registry (mc_items.normalize_item);
    an unresolvable item returns None so the task falls through to L3.
  - A param the rule cannot extract returns None, never a guessed value.
  - goto_and_scan requires an explicit coordinate triple AND a "for T" target
    (WideSearchBehavior rejects a blank target, so a bare "scan the area"
    must fall through rather than fabricate one).
"""

from __future__ import annotations

import re
from typing import Any

from mc_items import normalize_item

log = __import__("logging").getLogger("aibot.skill-matcher")

# Seed skill -> deterministic rule. Each returns the SKILL directive's `extra`
# map (param name -> value) or None. Param names MUST match
# l3_planner._SEED_SKILLS so the seed's SkillParams.substitute binds them.
_RULES: list[tuple[str, "Any"]] = []  # filled at module bottom by register()

_COORD = re.compile(r"\(?\s*(-?\d{1,6})\s*[,\s]\s*(-?\d{1,6})\s*[,\s]\s*(-?\d{1,6})\s*\)?")
_NUM = re.compile(r"\b(\d{1,3})\b")

# Leading/trailing filler stripped from an extracted item segment. Keep it a
# closed set — never strip a word that could be part of a real item id. Each
# alternative is a WHOLE word (boundaries on both sides) so a filler like
# "in"/"all" cannot eat the tail of "pumpkin"/the head of "alloy".
_LEAD_FILLER = re.compile(
    r"^(?:\s*\b(?:a|an|the|some|all|out|up|down|of|them|it|its|then|and|to|for|"
    r"store|stored|away|into|onto|at|in)\b)+", re.IGNORECASE)
_TRAIL_FILLER = re.compile(
    r"(?:\s*\b(?:and|then|to|for|them|it|its|store|stored|away|up|down|out|into|"
    r"onto|at|in|the|a|an|some|all|of)\b)+$", re.IGNORECASE)


def _clamp_count(n: int | None) -> str:
    """Count must be 1..64 (the mod's own range); default 1 when unspecified."""
    if n is None:
        return "1"
    return str(max(1, min(64, int(n))))


def _candidates(clean: str):
    """Try progressively simpler ids — "diamonds" → "diamond", "iron_ore_blocks"
    → "iron_ore". Only a candidate that actually resolves is accepted, so a
    wrong de-pluralisation/de-suffixing still yields None (never a fake id).
    The plural rule runs before the "blocks" rule so "iron_blocks" resolves to
    the storage block "iron_block", not the raw material "iron"."""
    yield clean
    if clean.endswith("s") and not clean.endswith("ss"):
        yield clean[:-1]
        if clean.endswith("ies"):
            yield clean[:-3] + "y"
    # "<ore> blocks" phrasing: "iron ore blocks" names the ore, "blocks" is
    # just a container word. Only reachable when the full/plural ids failed.
    if clean.endswith("_blocks"):
        yield clean[: -len("_blocks")]


def _resolve(name: str | None) -> str | None:
    """Resolve a human item phrase ("iron ore") to a registry id
    ("minecraft:iron_ore"). None when unresolvable — caller falls through."""
    if not name:
        return None
    clean = re.sub(r"\s+", "_", name.strip().lower())
    clean = clean.strip("._- ,;:!?\"'")
    if not clean:
        return None
    for cand in _candidates(clean):
        full, ok = normalize_item(cand)
        if ok:
            return full if ":" in full else f"minecraft:{full}"
    return None


def _clean_segment(seg: str) -> str:
    """Extract the material noun from a captured phrase segment."""
    seg = _LEAD_FILLER.sub("", seg.strip())
    seg = _TRAIL_FILLER.sub("", seg)
    # Drop any embedded count ("5 iron ingot" -> "iron ingot") that the fillers
    # missed because a number sat right after the verb.
    seg = re.sub(r"^\s*\d+\s*", "", seg)
    return re.sub(r"\s+", " ", seg).strip()


def _first_count(t: str) -> str:
    m = _NUM.search(t)
    return _clamp_count(int(m.group(1)) if m else None)


# ── Per-skill rules ────────────────────────────────────────────────────────


def _mine_and_smelt(t: str) -> dict[str, str] | None:
    if "mine" not in t or "smelt" not in t:
        return None
    m = re.search(r"\bmine\b(.*?)\bsmelt", t)
    if not m:
        return None
    item = _resolve(_clean_segment(m.group(1)))
    if item is None:
        return None
    return {"target": item, "count": _first_count(m.group(1))}


def _goto_and_scan(t: str) -> dict[str, str] | None:
    if not re.search(r"\bscan|search|explore|survey\b", t):
        return None
    c = _COORD.search(t)
    if not c:
        return None
    m = re.search(r"\bfor\s+(.+?)(?:\s+(?:around|near|in|at)\b|$)", t)
    target = _resolve(_clean_segment(m.group(1))) if m else None
    if target is None:
        return None
    return {"x": c.group(1), "y": c.group(2), "z": c.group(3), "target": target}


def _search_and_loot(t: str) -> dict[str, str] | None:
    if not re.search(r"\bsearch|loot\b", t):
        return None
    if not re.search(r"\bchest|container|barrel|shulker\b", t):
        return None
    m = re.search(r"\bfor\s+(.+?)(?:\s+(?:in|from|around|near)\b|$)", t)
    item = _resolve(_clean_segment(m.group(1))) if m else None
    if item is None:
        return None
    return {"item": item, "count": _first_count(t)}


def _harvest_and_store(t: str) -> dict[str, str] | None:
    m = re.search(r"\b(?:harvest|farm)\b", t)
    if not m:
        return None
    item = _resolve(_clean_segment(t[m.end():]))
    if item is None:
        return None
    return {"crop": item, "count": _first_count(t[m.end():])}


def _resupply_network(t: str) -> dict[str, str] | None:
    if not re.search(r"\bsend|give|deliver|resupply\b", t):
        return None
    m = re.search(r"\b(?:send|give|deliver|resupply)\b\s*(.+?)\s+(?:to|for)\s+([a-zA-Z0-9_]+)\s*$", t)
    if not m:
        return None
    item = _resolve(_clean_segment(m.group(1)))
    if item is None:
        return None
    return {"item": item, "count": _first_count(m.group(1)), "to": m.group(2).lower()}


# ── cultivate duration parsing ──────────────────────────────────────────────
# The skill's `seconds` param must honour "2 hours" / "two hours" / "90 minutes",
# not just a bare 1-3 digit number (which read "two hours" as no-number → the
# 30s default, and "2 hours" as 2 *seconds*). Word numbers cover common spoken
# durations; digits cover the rest; a unit maps to a ×1/×60/×3600 multiplier.
# No duration phrase → None (the caller keeps the skill default).

_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}

_DURATION = re.compile(
    r"\b(\d{1,6}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty)\s*"
    r"(hours?|hrs?|minutes?|mins?|seconds?|secs?|h|m|s)?",
    re.IGNORECASE,
)

_UNIT_MULT = {
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
}

# Mirror CultivateBehavior.MAX_SECONDS (24h) so a duration the agent extracts
# is never silently larger than what the mod will actually run.
MAX_CULTIVATE_SECONDS = 86400


def _parse_duration(t: str) -> int | None:
    """'2 hours' / 'two hours' / '90 minutes' / '45' → seconds; None when the
    text carries no duration phrase (the caller keeps the skill default)."""
    m = _DURATION.search(t)
    if not m:
        return None
    raw = m.group(1)
    n = int(raw) if raw.isdigit() else _WORD_NUM.get(raw.lower())
    if n is None:
        return None
    mult = _UNIT_MULT.get((m.group(2) or "").lower(), 1)
    secs = n * mult
    return secs if secs > 0 else None


def _cultivate(t: str) -> dict[str, str] | None:
    """The hive's FE skill: 'cultivate'/'cultivation' orders a CULTIVATE
    directive (a bounded hold, `seconds`). No items, no XP — the FE transfer is
    the point, so there is nothing to resolve. A duration phrase sets `seconds`;
    otherwise the skill's own default (30s) applies."""
    if not re.search(r"\bcultivat\w*\b", t):
        return None
    secs = _parse_duration(t) or 30
    return {"seconds": str(max(1, min(MAX_CULTIVATE_SECONDS, secs)))}


_RULES = [
    ("mine_and_smelt", _mine_and_smelt),
    ("goto_and_scan", _goto_and_scan),
    ("search_and_loot", _search_and_loot),
    ("harvest_and_store", _harvest_and_store),
    ("resupply_network", _resupply_network),
    ("cultivate", _cultivate),
]


def match(text: str) -> dict[str, Any] | None:
    """Deterministic skill match for a task/subtask phrase.

    Returns {"kind": "SKILL", "target": <skill_id>, "extra": {param: value}}
    on a confident hit, else None (caller falls through to L3). The returned
    dict is exactly the shape of a SKILL directive."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text).strip().lower())
    if not t:
        return None
    for skill_id, rule in _RULES:
        try:
            extra = rule(t)
        except Exception as e:  # noqa: BLE001 — a bad rule must never break planning
            log.debug("skill-matcher rule %s raised: %s", skill_id, e)
            continue
        if extra:
            log.info("skill-match: %r -> %s (%r)", t[:80], skill_id, extra)
            return {"kind": "SKILL", "target": skill_id, "extra": extra}
    return None
