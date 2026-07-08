"""Deterministic fast-path planner.

For a narrow set of unambiguous command shapes ("mine 16 iron ore",
"goto 100 64 -200", "teleport to the nether"), skip L3 entirely: build the
Plan directly with pre-baked directives on the subtask. Cuts plan latency
for the most common commands from ~15-45s of LLM time to ~0.

Precision over recall: patterns are anchored to the WHOLE command. Anything
with extra clauses, multiple actions, or fuzzy phrasing falls through
(returns None) to the normal L3 planning path. A wrong fast-path guess is
also self-healing — if the pre-baked directive fails, the retry path
(attempts > 0) routes through L3 exec as usual.

Criteria strings are written to match criteria_eval's Strategy-1 regexes so
completion checks are also LLM-free:
  "inventory has N <item>"  → inventory query
  "bot at (x, y, z)"        → position query
"""
from __future__ import annotations

import datetime
import logging
import re

from plan_schema import Plan, Subtask

log = logging.getLogger("aibot.fast-planner")

_DIM_ALIASES = {
    "nether": "minecraft:the_nether",
    "the nether": "minecraft:the_nether",
    "end": "minecraft:the_end",
    "the end": "minecraft:the_end",
    "overworld": "minecraft:overworld",
    "the overworld": "minecraft:overworld",
}

# Words where a trailing "s" is part of the item name, not a plural.
_KEEP_TRAILING_S = {
    "glass", "grass", "moss", "brass", "bass", "cactus", "quartz_glass",
    "seagrass", "tallgrass", "netherbrick", "bookshelf",  # (defensive extras)
}

_IRREGULAR_PLURALS = {
    "torches": "torch",
    "ores": "ore",
    "pickaxes": "pickaxe",
    "axes": "axe",
    "shovels": "shovel",
    "swords": "sword",
    "potatoes": "potato",
    "arrows": "arrow",
    "planks": "planks",       # planks is already the item id
    "bricks": "bricks",       # same
    "logs": "log",
    "diamonds": "diamond",
    "emeralds": "emerald",
    "ingots": "ingot",
}


def _norm_item(raw: str) -> str:
    """'iron ore' → 'minecraft:iron_ore'; 'Torches' → 'minecraft:torch'."""
    s = raw.strip().lower().rstrip(".,!")
    s = re.sub(r"\s+", "_", s)
    if ":" in s:
        return s
    # De-pluralize the final word segment
    parts = s.rsplit("_", 1)
    last = parts[-1]
    if last in _IRREGULAR_PLURALS:
        last = _IRREGULAR_PLURALS[last]
    elif last.endswith("s") and last not in _KEEP_TRAILING_S and not last.endswith("ss"):
        last = last[:-1]
    parts[-1] = last
    s = "_".join(parts)
    return f"minecraft:{s}"


# (regex, directive_kind). Whole-string anchored, count required for the
# gather-verbs so vague commands ("mine some iron") fall through to L3.
_GATHER_PATTERNS = [
    (re.compile(r"^(?:please\s+)?mine\s+(\d+)\s*x?\s+(.+?)\s*$", re.I), "MINE"),
    (re.compile(r"^(?:please\s+)?craft\s+(\d+)\s*x?\s+(.+?)\s*$", re.I), "CRAFT"),
    (re.compile(r"^(?:please\s+)?smelt\s+(\d+)\s*x?\s+(.+?)\s*$", re.I), "SMELT"),
    (re.compile(r"^(?:please\s+)?channel\s+(\d+)\s*x?\s+(.+?)\s*$", re.I), "CHANNEL"),
    (re.compile(r"^(?:please\s+)?farm\s+(\d+)\s*x?\s+(.+?)\s*$", re.I), "FARM"),
]

_GOTO_PATTERN = re.compile(
    r"^(?:please\s+)?(?:go\s*to|goto|move\s+to|walk\s+to)\s+"
    r"(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)\s*$", re.I)

_TELEPORT_PATTERN = re.compile(
    r"^(?:please\s+)?(?:teleport|tp|travel)\s+to\s+(?:the\s+)?(nether|end|overworld)\s*$", re.I)


def _one_subtask_plan(bot_name: str, task: str, description: str,
                      criteria: str, directives: list[dict]) -> Plan:
    return Plan(
        task=task,
        bot=bot_name,
        created_at=datetime.datetime.utcnow().isoformat(),
        status="executing",
        subtasks=[Subtask(
            id=1,
            description=description,
            criteria=criteria,
            status="pending",
            directives=directives,   # pre-baked → orchestrator skips L3 exec
        )],
        current_subtask_id=1,
    )


def try_plan(bot_name: str, task: str) -> Plan | None:
    """Return a ready Plan for recognized command shapes, else None."""
    text = task.strip()

    for pattern, kind in _GATHER_PATTERNS:
        m = pattern.match(text)
        if m:
            count = int(m.group(1))
            item = _norm_item(m.group(2))
            verb = kind.lower()
            log.info("[%s] fast-path %s: %dx %s", bot_name, kind, count, item)
            return _one_subtask_plan(
                bot_name, task,
                description=f"{verb} {count}x {item}",
                criteria=f"inventory has {count} {item}",
                directives=[{"kind": kind, "target": item, "count": count}],
            )

    m = _GOTO_PATTERN.match(text)
    if m:
        x, y, z = int(m.group(1)), int(m.group(2)), int(m.group(3))
        log.info("[%s] fast-path GOTO: (%d,%d,%d)", bot_name, x, y, z)
        return _one_subtask_plan(
            bot_name, task,
            description=f"go to ({x}, {y}, {z})",
            criteria=f"bot at ({x}, {y}, {z})",
            directives=[{"kind": "GOTO", "x": x, "y": y, "z": z}],
        )

    m = _TELEPORT_PATTERN.match(text)
    if m:
        dim = _DIM_ALIASES.get(m.group(1).lower())
        if dim:
            log.info("[%s] fast-path TELEPORT: %s", bot_name, dim)
            return _one_subtask_plan(
                bot_name, task,
                description=f"teleport to {dim}",
                criteria=f"bot in dimension {dim}",
                directives=[{
                    "kind": "TELEPORT", "x": 0, "y": 70, "z": 0,
                    "extra": {"dimension": dim},
                }],
            )

    return None
