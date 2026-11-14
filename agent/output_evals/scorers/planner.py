"""Planner, exec and replan scorers: parse, schema, and the kind/param surface.

The surface is taken from the agent's own `action_binding` module rather than a
copy, so the scorer cannot drift from what the dispatch path actually accepts.
An unreadable surface is an error, never a pass.
"""
from __future__ import annotations

from .common import (FAIL, PASS, UNSCORABLE, Result, check_kind_surface,
                     parse_json)

_SURFACE = None
_SURFACE_ERROR = ""


def _load_surface():
    """(kinds, error). The kinds come from the agent; params from _ALLOWED_ARGS."""
    global _SURFACE, _SURFACE_ERROR
    if _SURFACE is not None or _SURFACE_ERROR:
        return _SURFACE, _SURFACE_ERROR
    try:
        from agent import action_binding as ab  # type: ignore
    except Exception as e:  # pragma: no cover - import path guard
        try:
            import action_binding as ab  # type: ignore
        except Exception as e2:
            _SURFACE_ERROR = f"could not import action_binding: {e2}"
            return None, _SURFACE_ERROR
    kinds = getattr(ab, "BINDABLE_KINDS", None)
    args = getattr(ab, "_ALLOWED_ARGS", None)
    if not kinds or not args:
        _SURFACE_ERROR = "action_binding exports no BINDABLE_KINDS/_ALLOWED_ARGS"
        return None, _SURFACE_ERROR
    _SURFACE = {k: set(args) for k in kinds}
    return _SURFACE, ""


def reset_surface_cache():
    """For tests: forget the cached surface."""
    global _SURFACE, _SURFACE_ERROR
    _SURFACE, _SURFACE_ERROR = None, ""


def _unscorable(why):
    return Result(UNSCORABLE, why)


# The model IS asked for SKILL: the EXEC prompt says "emit exactly ONE directive
# of kind SKILL" (l3_planner.py:517) and its worked example is that shape (:534),
# plan_orchestrator.py:1056 executes a model-emitted SKILL, and mod
# DirectiveType.java:33 declares it. So a SKILL directive is the PREFERRED answer,
# not an off-surface kind -- scoring it as a fail was a scorer bug.
#
# BINDABLE_KINDS is deliberately left alone here: whether the *action binder* can
# bind SKILL/AREA_LOOT is a separate agent finding. This exception exists in the
# scorer because the model is asked for it, which is a different question from
# whether the binder accepts it.
SKILL_KIND = "SKILL"


def _check_skill_directive(item):
    """A model-emitted SKILL must name a non-empty skill id.

    The id rides in `target` (l3_planner.py:534). `extra` may carry the skill's
    own slots, which are skill-defined rather than part of BINDABLE_KINDS'
    parameter lists, so they are not checked against the surface.
    """
    target = item.get("target")
    if not isinstance(target, str) or not target.strip():
        return "SKILL has no skill id in `target`"
    return None


def score_exec(output):
    """`{"directives":[{kind, ...}]}` -- non-empty, every kind allowed.

    SKILL is allowed even though it is outside BINDABLE_KINDS: the model is
    asked to prefer it (see SKILL_KIND above).
    """
    surface, err = _load_surface()
    if err:
        return _unscorable(err)
    value, perr = parse_json(output)
    if perr:
        return Result(FAIL, perr)
    if not isinstance(value, dict):
        return Result(FAIL, f"expected an object, got {type(value).__name__}")
    directives = value.get("directives")
    if not isinstance(directives, list):
        return Result(FAIL, "no `directives` list")
    if not directives:
        return Result(FAIL, "`directives` is empty")
    surface_going, skill_going = [], []
    for item in directives:
        if isinstance(item, dict) and str(item.get("kind", "")).upper() == SKILL_KIND:
            skill_going.append(item)
        else:
            surface_going.append(item)
    problems = check_kind_surface(surface_going, surface)
    for i, item in enumerate(skill_going):
        bad = _check_skill_directive(item)
        if bad:
            problems.append(f"SKILL item {i}: {bad}")
    if problems:
        return Result(FAIL, "; ".join(problems), {"n": len(directives)})
    return Result(PASS, "", {"n": len(directives), "skill": len(skill_going)})


def score_replan(output):
    """A replacement subtask: parses to an object carrying the subtask fields."""
    value, perr = parse_json(output)
    if perr:
        return Result(FAIL, perr)
    if not isinstance(value, dict):
        return Result(FAIL, f"expected an object, got {type(value).__name__}")
    # A replan may be nested under a key by the prompt; accept either shape but
    # require the fields a Subtask needs.
    body = value
    for key in ("subtask", "replacement", "replacement_subtask"):
        if isinstance(value.get(key), dict):
            body = value[key]
            break
    missing = [f for f in ("id", "description", "criteria") if f not in body]
    if missing:
        return Result(FAIL, f"subtask missing {missing}")
    return Result(PASS, "")


def _plan_directives(subtask):
    """Directives a subtask may carry, whichever key the plan shape uses."""
    out = []
    d = subtask.get("directives")
    if isinstance(d, list):
        out.extend(d)
    if isinstance(subtask.get("directive"), dict):
        out.append(subtask["directive"])
    return out


def score_plan(output):
    """A plan: schema-valid, with every subtask's directives inside the surface."""
    surface, err = _load_surface()
    if err:
        return _unscorable(err)
    value, perr = parse_json(output)
    if perr:
        return Result(FAIL, perr)
    if not isinstance(value, dict):
        return Result(FAIL, f"expected an object, got {type(value).__name__}")

    kind = value.get("kind")
    if kind in ("clarify", "refuse"):
        # Correct-on-purpose only when the case is labelled so; the scorer's
        # job is the surface, the caller supplies the label.
        return Result(PASS, f"{kind} response", {"shape": kind})

    if "task" not in value or not isinstance(value.get("subtasks"), list):
        return Result(FAIL, "plan needs `task` and a `subtasks` list")
    subtasks = value["subtasks"]
    if not subtasks:
        return Result(FAIL, "plan has no subtasks")

    problems = []
    for i, st in enumerate(subtasks):
        if not isinstance(st, dict):
            problems.append(f"subtask {i} is not an object")
            continue
        for f in ("id", "description", "criteria"):
            if f not in st:
                problems.append(f"subtask {i} missing {f}")
        problems.extend(f"subtask {i}: {p}" for p in
                        check_kind_surface(_plan_directives(st), surface))
    if problems:
        return Result(FAIL, "; ".join(problems), {"n_subtasks": len(subtasks)})
    return Result(PASS, "", {"n_subtasks": len(subtasks)})


SCORERS = {"plan": score_plan, "exec": score_exec, "replan": score_replan}
