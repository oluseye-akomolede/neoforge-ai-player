"""Action binding for scripts (M2 task 3.2).

A script proposes actions; this module decides which ones the agent may run,
and refuses the rest *before* anything is dispatched. The refusal is the
product here: a script that invents an action name must fail loudly and
execute nothing, not fall through to a handler that treats an unknown kind as
a no-op.

The accepted set is the agent's real dispatch set, read from the consumer:
`Agent._dispatch` (agent.py:896-989) handles nine kinds itself before falling
through to `_run_directive` with the mod's directive vocabulary. The union of
those two, and nothing else, is bindable.

This module holds the vocabulary rather than importing it from agent.py,
because importing agent.py drags in psycopg2 and uvicorn and would make this
untestable where tests must run. `test_action_binding.py` pins the sets against
the live source so the copy cannot drift silently -- the same failure mode as
the `load_profile` citation and the stale retry constant.
"""
from __future__ import annotations

# Kinds `Agent._dispatch` handles agent-side, before any mod call.
#
# EQUIP and EQUIP_ALL both map to the mod's synchronous equip_all action.
# VAULT_STORE/STORE and VAULT_WITHDRAW/WITHDRAW and DROP/DISCARD are the agent's
# own L1 paths, so the mod never sees these names.
AGENT_SIDE_KINDS = frozenset({
    "EQUIP", "EQUIP_ALL",
    "PROVISION_TERMINAL",
    "ASK_PLAYER",
    "VAULT_STORE", "STORE",
    "VAULT_WITHDRAW", "WITHDRAW",
    "DROP", "DISCARD",
})

# The mod's directive vocabulary, as the planner sends it. Kept in sync with
# l3_planner._VALID_DIRECTIVE_KINDS by test_bindable_set_matches_source().
MOD_DIRECTIVE_KINDS = frozenset({
    "MINE", "GATHER", "GOTO", "FOLLOW", "COMBAT", "CRAFT", "SMELT", "ENCHANT",
    "BREW", "CHANNEL", "SEND_ITEM", "BUILD", "FARM", "CONTAINER_PLACE",
    "CONTAINER_SEARCH", "CONTAINER_STORE", "CONTAINER_WITHDRAW", "TELEPORT",
    "IDLE", "PATROL", "WIDE_SEARCH", "LOCATE", "STORE_ALL", "ME_STORE",
    "ME_WITHDRAW", "CRAFT_REQUEST", "MEDITATE", "CULTIVATE",
    "MOUNT_VEHICLE", "DISMOUNT_VEHICLE", "DRIVE_VEHICLE", "REQUISITION",
    "FUSE_BLOCK", "MANAGE_FUSION", "UNFUSE_BLOCK",
})

BINDABLE_KINDS = AGENT_SIDE_KINDS | MOD_DIRECTIVE_KINDS

# Arguments a script may carry on an action. Anything else is dropped rather
# than forwarded: `kind` becomes `type` at the dispatch boundary, and letting a
# script set `type` directly would let it reach a handler the binding refused.
_ALLOWED_ARGS = frozenset({"target", "count", "radius", "x", "y", "z", "extra"})


class RefusedAction(Exception):
    """An action the agent will not run. Carries why, so the script's author
    can fix it rather than guess."""


def bind_action(action):
    """Validate one script-proposed action and return a dispatchable directive.

    Raises `RefusedAction` for anything the agent cannot run. Returns a dict
    with `kind` normalised to upper case and only allow-listed arguments.
    """
    if not isinstance(action, dict):
        raise RefusedAction(f"action must be an object, got {type(action).__name__}")

    raw = action.get("kind", action.get("action"))
    if not isinstance(raw, str) or not raw.strip():
        raise RefusedAction(f"action has no 'kind': {action!r}")

    kind = raw.strip().upper()
    if kind not in BINDABLE_KINDS:
        raise RefusedAction(
            f"unknown action {raw!r}: not in the agent's dispatch set "
            f"({len(BINDABLE_KINDS)} kinds: {len(AGENT_SIDE_KINDS)} agent-side, "
            f"{len(MOD_DIRECTIVE_KINDS)} mod)"
        )

    bound = {"kind": kind}
    for key, value in action.items():
        if key in ("kind", "action"):
            continue
        if key not in _ALLOWED_ARGS:
            # Silent dropping is the failure this module exists to prevent, so
            # an unrecognised argument is a refusal, not a shrug.
            raise RefusedAction(
                f"action {kind} carries unsupported argument {key!r}; "
                f"allowed: {', '.join(sorted(_ALLOWED_ARGS))}"
            )
        bound[key] = value
    return bound


def bind_actions(actions):
    """Bind a script's action list.

    Returns `(bound, refusals)`. Refusals are collected rather than raised so a
    script that emits one bad action out of five still runs the other four, and
    the outcome is visible. An empty action list is a normal result, not a
    refusal -- the silence case depends on it.
    """
    if not isinstance(actions, list):
        return [], [{"error": f"actions must be a list, got {type(actions).__name__}"}]

    bound, refusals = [], []
    for i, action in enumerate(actions):
        try:
            bound.append(bind_action(action))
        except RefusedAction as e:
            refusals.append({"index": i, "kind": (action or {}).get("kind")
                             if isinstance(action, dict) else None,
                             "error": str(e)})
    return bound, refusals


def to_directive(bound):
    """`kind` -> `type`, the shape `Agent._dispatch` expects.

    Refuses if a caller has smuggled `type` in: binding already rejected it, so
    its presence here means something bypassed `bind_action`.
    """
    if "type" in bound:
        raise RefusedAction("bound action already carries 'type' - bypassed bind_action")
    out = dict(bound)
    out["type"] = out.pop("kind")
    return out
