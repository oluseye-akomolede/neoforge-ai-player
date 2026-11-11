"""Agent-side directive dispatch for coded scripts.

The runner deliberately does NOT validate directive names: the set belongs to
the game, and the runner should not carry a copy of it (contract §4.1). So the
name is resolved here, at the moment the action is applied, on the side that
owns the set.

Two behaviours, both grounded in the mod's source rather than in a guess:

  * CASE is normalised to upper. `HttpApiServer.java:1341` already does
    `body.get("type").getAsString().toUpperCase()` before `DirectiveType.valueOf`,
    so a script naming "mine" works against this mod today. Normalising here
    makes the agent and the mod agree instead of relying on the mod's hidden
    forgiveness, and keeps the log line showing the same spelling the mod used.

  * UNKNOWN names are refused HERE. `DirectiveType.valueOf` throws
    IllegalArgumentException inside the request handler, which the agent sees as
    an HTTP 500 with no name in it. Refusing locally turns that into an error
    that names the directive and the accepted set.

    An earlier draft of M2-PLAN said a lowercase name "would reach the mod and
    fail there". That is false on this mod revision -- see the first bullet.
    A test written against that premise would have asserted a rejection that
    does not, and should not, happen.
"""

from __future__ import annotations

# The mod's DirectiveType, verified against
# src/main/java/com/sigmastrain/aiplayermod/brain/DirectiveType.java (37
# constants). Note this is NOT the skill-leaf set (35): a name can be a valid
# DirectiveType and still not be reachable via api.do, which is enforced at
# dispatch where the payload is visible. Keep this list exact; the mod is
# exact after upper-casing.
DIRECTIVE_KINDS = frozenset({
    "AREA_LOOT",
    "BREW",
    "BUILD",
    "CHANNEL",
    "COMBAT",
    "CONTAINER_PLACE",
    "CONTAINER_SEARCH",
    "CONTAINER_STORE",
    "CONTAINER_WITHDRAW",
    "CRAFT",
    "CRAFT_REQUEST",
    "CULTIVATE",
    "DISMOUNT_VEHICLE",
    "DRIVE_VEHICLE",
    "ENCHANT",
    "FARM",
    "FOLLOW",
    "FUSE_BLOCK",
    "GATHER",
    "GOTO",
    "IDLE",
    "LOCATE",
    "MANAGE_FUSION",
    "ME_STORE",
    "ME_WITHDRAW",
    "MEDITATE",
    "MINE",
    "MOUNT_VEHICLE",
    "PATROL",
    "REQUISITION",
    "SEND_ITEM",
    "SKILL",
    "SMELT",
    "STORE_ALL",
    "TELEPORT",
    "UNFUSE_BLOCK",
    "WIDE_SEARCH",
})


class UnknownDirective(ValueError):
    """A script named a directive the mod does not define."""


def normalise_directive_name(name) -> str:
    """Return the canonical UPPERCASE name, or raise UnknownDirective.

    Mirrors the mod's own `.toUpperCase()` so both sides agree, and refuses
    anything outside DIRECTIVE_KINDS rather than letting the mod throw a
    nameless 500. Surrounding whitespace is stripped first: a trailing newline
    from a script literal is a plausible typo, not a different directive.
    """
    if not isinstance(name, str):
        raise UnknownDirective(
            f"directive name must be a string, got {type(name).__name__}: {name!r}")

    canonical = name.strip().upper()
    if canonical not in DIRECTIVE_KINDS:
        raise UnknownDirective(
            f"unknown directive {name!r} (normalised {canonical!r}); "
            f"the mod defines {len(DIRECTIVE_KINDS)} directive kinds")
    return canonical
