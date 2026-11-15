"""Rebuild the L3 system prompt from l3_planner, instead of replaying it.

The replay path sends `case.prompt_system` -- the text the model saw when the
call was RECORDED. That is the right input for "how does today's model answer
the same question", and the wrong one for "how does today's PROMPT do": a
prompt edit changes l3_planner.py, not the corpus, so a recorded prompt makes
every prompt change invisible to the eval. This module is the opt-in other leg.

It is a copy of the call site's format arguments and nothing else:

  - plan   -> l3_planner.call_plan:   bot_name, persona, dimensions, skills
  - replan -> l3_planner.call_replan: bot_name, persona, plan_json,
                                      subtask_json, error, attempts, subtask_id

Every value comes from the case's own record. Where a value cannot be
recovered, the case is reported UNSCORABLE: this leg's whole claim is "the
model was sent the current source prompt", and a rebuilt prompt that quietly
dropped a section would be a different input wearing the same name -- the
model would be scored on a prompt the product never sends.

The one value that is not in the record is `skills`, which comes from a live
GET /skills at the call site. The eval Job has no API server, so the caller
supplies it (empty is what `_skills_lines()` returns when the API is down,
which is a real state the product runs in, not a guess). The case gains the
`skills_section: "supplied"` / `"not-recorded"` key saying which happened.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

# `extract` and the prompt module are imported INSIDE the functions that use
# them, on purpose. This module is imported by run.py at start-up, and both of
# those imports fail loudly on purpose: `extract` is never the one to blame,
# but `l3_planner` pulls the agent's own config and network stack. Keeping the
# imports local means a machine without them still runs the replay leg, and
# only the rebuild leg reports why it cannot.

# A recorded prompt shorter than this cannot have carried its sections, so it
# is not usable as evidence that a value is missing.
_MIN_RECORDED = 200


class Unscorable(Exception):
    """The values this case needs to rebuild its prompt are not in the record."""


def differs(case, expected, recorded):
    """(differs, how) -- what the rebuild changes about the recorded prompt.

    `not-comparable` is its own outcome, not `same`: a case whose recorded
    prompt is empty cannot be said to agree with the rebuild, and 25 cases
    reported as `same` against an empty string is the instrument that reads
    nothing and prints a verdict.
    """
    from output_evals.extract import redact

    recorded = (recorded or "").strip()
    if len(recorded) < _MIN_RECORDED:
        return None, "not-comparable: recorded prompt empty or truncated"
    if redact(expected).strip() == recorded:
        return False, "same"
    a = hashlib.sha256(redact(expected).encode()).hexdigest()[:12]
    b = hashlib.sha256(recorded.encode()).hexdigest()[:12]
    return True, f"differs: rebuilt {len(expected)}B sha {a}, recorded {len(recorded)}B sha {b}"


def _persona(planner, bot_name):
    return planner.BOT_PERSONAS.get(bot_name, "generalist")


_SKILL_HEAD = "Registered skills (each runs end-to-end as ONE deterministic directive):\n"


def skills_from_prompt(text):
    """The skill catalog the recorded plan prompt listed, or "" if it listed none.

    Same reasoning as the dimension list: this is the section the model was
    SHOWN, so rebuilding with an empty catalog would ask it to plan without the
    skills the answer was judged against. None means "no such section", which is
    an unbuildable case; "" means the section was there and empty, which is what
    `_skills_lines()` returns when the API is down and is a real shape.
    """
    if not text:
        return None
    idx = text.find(_SKILL_HEAD)
    if idx < 0:
        return None
    rest = text[idx + len(_SKILL_HEAD):]
    lines = []
    for line in rest.splitlines():
        if line.strip() and not line.startswith(" "):
            break                       # the next unindented paragraph
        lines.append(line)
    return "\n".join(lines).strip()


def skills_from_env():
    """The `skills` section to supply. Empty when unset -- the API-down shape.

    A file rather than an env var: the section is a multi-line skill catalog,
    and the Job ships it as a ConfigMap key.
    """
    path = os.environ.get("EVALS_SKILLS_FILE")
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def rebuild(case, planner, skills=None):
    """Rebuild the CURRENT source system prompt for `case` and attach its verdict.

    Mutates and returns the case: `prompt_system` becomes the rebuilt text and
    `recorded_prompt_system` keeps the original, so the case file sent to the
    Job carries both and the report can compare them without the corpus.
    """
    # The INPUT is whichever field holds the recorded prompt. A case set built
    # without `--rebuild-from-source` carries it in `prompt_system`; one built
    # WITH it parks it in `recorded_prompt_system` and leaves `prompt_system`
    # empty, precisely so the Job -- not the extract -- decides the text. Read
    # `prompt_system` unconditionally and a deferred set rebuilds every case
    # from "" and marks it unscorable: the Job would score nothing and say so
    # only in a per-kind count.
    recorded = (case.prompt_system or case.recorded_prompt_system or "")
    if case.kind == "plan":
        case.prompt_system = _rebuild_plan(case, planner, skills, recorded)
    elif case.kind == "replan":
        case.prompt_system = _rebuild_replan(case, planner, recorded)
    else:
        # exec has no system prompt of this shape; nothing to rebuild.
        return case
    d, how = differs(case, case.prompt_system, recorded)
    case.recorded_prompt_system = recorded
    case.prompt_differs = d
    case.prompt_diff = how
    return case


_DIM_BULLET = re.compile(r"^\s*-\s+([a-z0-9_.\-]+:[a-z0-9_.\-]+)")
_DIM_SECTION = re.compile(
    r"(Available dimensions[^\n]*\n)((?:[ \t]*-[^\n]*\n)+)")


def dimensions_from_prompt(text):
    """The dimension ids the recorded plan prompt listed, or None.

    The call site passes `dimensions` from the live server; the record does not
    carry the list separately, but the prompt HAS it. Rebuilding with
    `_dim_lines(None)` instead would silently measure the candidate against the
    three vanilla defaults rather than the 15 dimensions the model actually
    saw -- a different prompt wearing a current one's name.
    """
    m = _DIM_SECTION.search(text or "")
    if not m:
        return None
    ids = [mm.group(1) for mm in (_DIM_BULLET.match(l) for l in m.group(2).splitlines())
           if mm]
    return ids or None


def _rebuild_plan(case, planner, skills, recorded=None):
    if not (case.bot or "").strip():
        raise Unscorable("plan: no bot in the record, so no persona")
    if not (case.prompt_user or "").strip():
        raise Unscorable("plan: no user prompt in the record")
    # The model saw the server's real dimension list, and the recorded prompt
    # is where it survives. Checked before formatting: an empty list would be
    # a prompt section the product never sends.
    recorded = case.prompt_system if recorded is None else recorded
    dims = dimensions_from_prompt(recorded)
    if not dims:
        raise Unscorable("plan: no dimension list in the recorded prompt")
    if skills is None:
        skills = skills_from_prompt(recorded)
        if skills is None:
            raise Unscorable("plan: no skills section in the recorded prompt")
    return planner._PLAN_SYSTEM_PROMPT.format(
        bot_name=case.bot,
        persona=_persona(planner, case.bot),
        dimensions=planner._dim_lines(dims),
        skills=skills,
    )


def _rebuild_replan(case, planner, recorded=None):
    """Rebuild from the subtask the model was ACTUALLY shown.

    Not from the plan the case scored: the replan prompt embeds the failed
    subtask's directives and its attempt count at the moment of the call, and
    the recorded response is the only place those survive.
    """
    if not (case.bot or "").strip():
        raise Unscorable("replan: no bot in the record, so no persona")

    # The prompt needs {plan_json} and {subtask_json}: the plan the bot was
    # following and the subtask that failed. Two places carry them, and the
    # second is the one that actually exists in production recordings:
    #
    #   1. the call record, as structured fields (a source that records them);
    #   2. the recorded PROMPT, which embeds both verbatim -- `Full plan: {...}`
    #      and `Failed subtask: {...}`. 271 of 271 replan calls in the corpus
    #      carry no structured fields and every one of them carries this text,
    #      so refusing them without reading it would make this leg score
    #      nothing while reporting a clean run.
    #
    # A case with neither is `synthesised` -- a hand-written response where no
    # plan ever existed -- and is unscorable, never filled in with an empty
    # object. Check the VALUES: Case defaults the fields to {}.
    plan = getattr(case, "recorded_plan", None) or {}
    subtask = getattr(case, "recorded_subtask", None) or {}
    if not plan or not subtask:
        plan, subtask = _from_recorded_prompt(
            case, need_plan=not plan, need_subtask=not subtask, recorded=recorded)
    if not isinstance(plan, dict) or not isinstance(subtask, dict):
        raise Unscorable("replan: recorded plan/subtask are not objects")
    if "id" not in subtask:
        raise Unscorable("replan: the failed subtask carries no id")

    try:
        return planner._REPLAN_SYSTEM_PROMPT.format(
            bot_name=case.bot,
            persona=_persona(planner, case.bot),
            plan_json=json.dumps(planner._compact_plan(planner.Plan.from_dict(plan)),
                                 indent=2),
            subtask_json=json.dumps(
                planner._compact_subtask(planner.Subtask.from_dict(subtask)), indent=2),
            error=subtask.get("error") or "(unknown)",
            attempts=subtask.get("attempts", 0),
            subtask_id=subtask["id"],
        )
    except (KeyError, TypeError, ValueError) as e:
        raise Unscorable(f"replan: could not rebuild from the record ({type(e).__name__}: {e})")


_PLAN_HEAD = "Full plan: "
_SUBTASK_HEAD = "Failed subtask: "


def _balanced_object(text, start):
    """The JSON object beginning at `text[start] == '{'`, or None.

    Brace counting, not a greedy regex: a subtask's `criteria` is free text and
    may contain a brace, and a greedy match would swallow the rest of the
    prompt and fail to parse -- turning a scorable case into an unscorable one
    for no reason a reader could see.
    """
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _embedded(text, head):
    """The object on the line(s) after `head`, parsed. None if absent."""
    idx = text.find(head)
    if idx < 0:
        return None
    brace = text.find("{", idx + len(head))
    if brace < 0:
        return None
    obj = _balanced_object(text, brace)
    if obj is None:
        return None
    try:
        parsed = json.loads(obj)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _from_recorded_prompt(case, need_plan, need_subtask, recorded=None):
    """Recover the plan and/or the failed subtask from the recorded prompt.

    Raises Unscorable naming what is missing and where the case came from.
    """
    # Same two-field rule as rebuild(): a deferred case set leaves
    # `prompt_system` empty and parks the recorded prompt in
    # `recorded_prompt_system`.
    text = recorded if recorded is not None else (case.prompt_system or "")
    text = text or ""
    plan = _embedded(text, _PLAN_HEAD) if need_plan else {}
    subtask = _embedded(text, _SUBTASK_HEAD) if need_subtask else {}
    if not plan or not subtask:
        missing = [n for n, v in (("plan", plan), ("subtask", subtask)) if not v]
        raise Unscorable(
            "replan: the record carries no " + " and no ".join(missing) +
            " -- neither as fields on the call nor embedded in the recorded "
            "prompt -- source=" + str(case.source or "unknown")
        )
    return plan, subtask


def attach_context(records, cases):
    """Fill in recorded_plan / recorded_subtask for replan cases, where the log has them.

    Returns the set of call_ids that got context. Replan cases come from three
    sources, and only one of them carries what the prompt needs:
      - `iface`      calls: the agent's interface recorded plan and subtask.
      - `recorded`   calls: a transcript replay recorded the prompt verbatim,
                     so the values are recoverable from it.
      - `synthesised`: the response is a hand-written fixture. NO plan and no
                     subtask ever existed, so these are unscorable on this leg
                     and the report says so rather than inventing them.
    """
    by_call = {}
    for rec in records:
        if rec.get("type") == "call" and rec.get("phase") == "replan":
            by_call[rec.get("call_id")] = rec
    filled = set()
    for c in cases:
        if c.kind != "replan":
            continue
        rec = by_call.get(c.call_id) or {}
        plan = rec.get("plan") or rec.get("recorded_plan")
        subtask = rec.get("failed_subtask") or rec.get("recorded_subtask")
        if isinstance(plan, dict) and isinstance(subtask, dict):
            c.recorded_plan, c.recorded_subtask = plan, subtask
            filled.add(c.call_id)
    return filled
