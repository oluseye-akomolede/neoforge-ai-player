#!/usr/bin/env python3
"""Tests for openspec change dispatch-must-start (row B defects 1 + 2).

Defect 1: on TEST 11-13 a plan dispatched kind SEARCH_AND_STORE, which is not a
directive kind. The mod never started it and the orchestrator dispatched anyway.

Defect 2: the same plan closed 'complete' because its criterion was
"holdings 0/0" — true of a bot that did nothing. Criteria were evaluated
whatever dispatch returned.

Real `_step`; only the L3 call and the dispatch boundary are controlled. Each
test asserts the property the spec names, and the negative case is written so
it FAILS against the old code (see the mutation note on each test).

Loaded by path so it runs without psycopg2/uvicorn, like test_action_binding.

Run: (ulimit -v 4194304; cd agent && nice -n 19 python3 test_dispatch_must_start.py)
"""
from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plan_orchestrator
import l3_planner
from plan_orchestrator import _dispatch_started
from plan_schema import Plan, Subtask

failures = 0


def check(label: str, cond: bool, detail: str = ""):
    global failures
    if cond:
        print(f"  PASS  {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def _plan(criteria="", n=1):
    return Plan(
        task="store the ore", bot="scout",
        created_at="2026-11-13T00:00:00", status="executing",
        subtasks=[Subtask(id=i + 1, description=f"s{i+1}", criteria=criteria)
                  for i in range(n)],
        current_subtask_id=1,
    )


def _run_step(plan, directives, dispatch, criteria="", l2_flags=None):
    """Drive one real _step. Returns (cont, dispatched_kinds, subtask, ev).

    l2_flags: when set, `_L2_MCP_URL` is pointed at a mock and every repair
    call returns a rendered directive carrying these flags — so the flags are
    collected by _step's OWN repair pass, which is the path under test.
    """
    dispatched = []

    def fake_exec(**kw):
        return ([dict(d) for d in directives], "call-1")

    def fake_dispatch(d):
        dispatched.append(str(d.get("kind", "")).upper())
        return dispatch(d)

    sub = plan.subtasks[0]
    sub.criteria = criteria or sub.criteria
    patches = [
        mock.patch.object(l3_planner, "call_exec", side_effect=fake_exec),
        mock.patch.object(plan_orchestrator.plan_store, "write"),
        mock.patch.object(plan_orchestrator.telemetry, "push"),
        mock.patch.object(plan_orchestrator, "evaluate_criteria",
                         return_value=(False, "mock", "not satisfied")),
    ]
    if l2_flags is not None:
        resp = mock.Mock(
            raise_for_status=mock.Mock(),
            json=mock.Mock(side_effect=lambda: {
                "rendered": {"directive": {"kind": "MINE", "target": "iron_ore"},
                             "flags": list(l2_flags)}}))
        patches += [
            mock.patch.object(plan_orchestrator, "_L2_MCP_URL", "http://l2"),
            mock.patch.object(plan_orchestrator.requests, "post", return_value=resp),
        ]
    ev = None
    for i, p in enumerate(patches):
        m = p.start()
        if i == 3:
            ev = m
    try:
        cont = plan_orchestrator._step(
            plan, sub, "m", fake_dispatch, lambda: "world", dim_list=[],
            cancel_event=None)
    finally:
        for p in reversed(patches):
            p.stop()
    return cont, dispatched, sub, ev


# ── 1. Unknown kinds are not dispatched ─────────────────────────────────────

def test_invented_kind_is_not_dispatched():
    """The 11-13 shape: SEARCH_AND_STORE is not a known kind.

    Fails on the old code: it dispatched it (dispatched == ['SEARCH_AND_STORE'])
    and the attempt went on to evaluate criteria.
    """
    print("1a. invented kind is not dispatched (TEST 2026-11-13)")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "SEARCH_AND_STORE"}], lambda d: "COMPLETED SEARCH_AND_STORE {}")

    check("no directive reached the mod", dispatched == [], f"dispatched={dispatched}")
    check("attempt failed with unknown_kind:<KIND>",
          sub.error == "unknown_kind:SEARCH_AND_STORE", f"error={sub.error!r}")
    check("criteria were not evaluated", ev.call_count == 0, f"calls={ev.call_count}")
    check("attempt was consumed", sub.attempts == 1, f"attempts={sub.attempts}")
    check("plan not failed outright on attempt 1", cont is True, f"cont={cont}")


def test_skill_is_not_refused_by_the_gate():
    """SKILL is emitted by the planner itself (_collapse_to_skill, :951).

    It is in neither BINDABLE_KINDS nor l3_planner's raw-kind vocabulary, so
    the unknown-kind gate must exempt it explicitly. Fails on the unexempted
    gate: every collapsed subtask would fail unknown_kind:SKILL.
    """
    print("1d. a collapsed SKILL subtask still dispatches")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "SKILL", "extra": {"spec": "gather wood"}}],
        lambda d: "COMPLETED SKILL {}")

    check("SKILL reached the dispatch path", dispatched == ["SKILL"],
          f"dispatched={dispatched}")
    check("SKILL not failed as unknown_kind",
          "unknown_kind" not in (sub.error or ""), f"error={sub.error!r}")
    check("criteria were evaluated for a started SKILL", ev.call_count == 1,
          f"calls={ev.call_count}")


def test_skill_with_spec_reaches_refine():
    """An exempted SKILL must reach its own dispatch path, not just pass the gate.

    _step routes a SKILL carrying an inline spec through
    _dispatch_skill_with_refine (:664) rather than plain dispatch_fn. Passing
    the gate is not enough: the directive has to land there.
    """
    print("1f. SKILL with a spec reaches _dispatch_skill_with_refine")
    plan = _plan()
    seen = []

    def fake_refine(d, dispatch_fn, model, bot, cancel_event=None):
        seen.append((d.get("kind"), (d.get("extra") or {}).get("spec")))
        return "COMPLETED SKILL {}"

    with mock.patch.object(plan_orchestrator, "_dispatch_skill_with_refine",
                           side_effect=fake_refine):
        _run_step(plan, [{"kind": "SKILL", "extra": {"spec": "gather wood"}}],
                  lambda d: "COMPLETED SKILL {}")

    check("SKILL was routed to refine, not plain dispatch",
          seen == [("SKILL", "gather wood")], f"seen={seen}")


def test_skill_synthesis_is_still_refused():
    """The exemption is for SKILL only, not a general hole.

    Guards against over-reach in the other direction: SKILL passing must not
    let an invented kind through alongside it.
    """
    print("1e. SKILL exemption does not admit other kinds")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "SKILL", "extra": {"spec": "x"}},
               {"kind": "SEARCH_AND_STORE"}],
        lambda d: "COMPLETED {}")

    check("mix refused on the unknown kind", dispatched == [],
          f"dispatched={dispatched}")
    check("mix failed naming SEARCH_AND_STORE",
          sub.error == "unknown_kind:SEARCH_AND_STORE", f"error={sub.error!r}")


def test_alias_still_dispatches():
    """EQUIP -> EQUIP_ALL is alias resolution, not an unknown kind.

    Guards the fix against over-reach: a kind that becomes known through the
    alias table MUST still dispatch. Fails if BINDABLE_KINDS is consulted
    before alias resolution.
    """
    print("1b. EQUIP alias still dispatches")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "EQUIP"}], lambda d: "COMPLETED EQUIP_ALL armor")

    check("EQUIP dispatched as EQUIP_ALL", dispatched == ["EQUIP_ALL"], f"dispatched={dispatched}")
    check("no unknown_kind error", not (sub.error or "").startswith("unknown_kind"),
          f"error={sub.error!r}")


def test_known_kind_dispatches():
    print("1c. a known mod kind dispatches unchanged")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "MINE", "target": "iron_ore"}], lambda d: "COMPLETED MINE {}",
        criteria="")

    check("MINE dispatched", dispatched == ["MINE"], f"dispatched={dispatched}")


def test_l2mcp_flag_is_honoured():
    """l2-mcp flagged unknown_kind; it is reachable, so fail-open does NOT apply.

    Fails on the old code: the flag was logged and discarded, and the directive
    dispatched.
    """
    print("1d. l2-mcp unknown_kind flag is honoured")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "MINE", "target": "iron_ore"}],
        lambda d: "COMPLETED MINE {}",
        l2_flags=["unknown_kind:TELEPORT_TO_NEAREST_VILLAGE"])

    check("flagged directive was not dispatched", dispatched == [], f"dispatched={dispatched}")
    check("failed with the flagged kind",
          sub.error == "unknown_kind:TELEPORT_TO_NEAREST_VILLAGE", f"error={sub.error!r}")


# ── 2. A subtask passes only if its dispatch started ────────────────────────

def test_never_started_cannot_satisfy_a_true_criterion():
    """The exact 11-13 completion: criterion true, nothing started.

    Fails on the old code: evaluate_criteria ran, saw holdings 0/0, and marked
    the subtask satisfied.
    """
    print("2a. never-started dispatch cannot satisfy 'holdings 0/0'")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "STORE_ALL"}],
        lambda d: "FAILED STORE_ALL directive_never_started",
        criteria="holdings 0/0 of minecraft:items")

    check("the directive WAS sent (so this is a start problem, not a kind one)",
          dispatched == ["STORE_ALL"], f"dispatched={dispatched}")
    check("criteria were not consulted", ev.call_count == 0, f"calls={ev.call_count}")
    check("subtask is not complete", sub.status != "complete", f"status={sub.status}")
    check("attempt failed with the dispatch reason",
          "directive_never_started" in (sub.error or ""), f"error={sub.error!r}")
    check("plan is not complete", plan.status != "complete", f"status={plan.status}")


def test_one_started_directive_still_evaluates_criteria():
    """The spec's second scenario: start beats a sibling's failure."""
    print("2b. one directive started -> criteria still evaluated")
    plan = _plan()
    results = iter(["FAILED MINE directive_never_started",
                    "COMPLETED GOTO {}"])
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "MINE", "target": "iron_ore"}, {"kind": "GOTO"}],
        lambda d: next(results), criteria="")

    check("both directives dispatched", len(dispatched) == 2, f"dispatched={dispatched}")
    check("criteria WERE evaluated", ev.call_count == 1, f"calls={ev.call_count}")
    check("no never-started failure recorded",
          "directive_never_started" not in (sub.error or ""), f"error={sub.error!r}")


def test_zero_directive_attempt_is_unchanged():
    """An empty attempt has nothing to start; behaviour must not change."""
    print("2c. zero-directive attempt unchanged")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(plan, [], lambda d: "", criteria="")

    check("nothing dispatched", dispatched == [], f"dispatched={dispatched}")
    check("criteria still evaluated", ev.call_count == 1, f"calls={ev.call_count}")


def test_started_but_failed_still_evaluates():
    """A directive that started and failed is a start: criteria decide."""
    print("2d. started-then-failed directive is not 'never started'")
    plan = _plan()
    cont, dispatched, sub, ev = _run_step(
        plan, [{"kind": "MINE", "target": "iron_ore"}],
        lambda d: "FAILED MINE directive_timeout after 5m", criteria="")

    check("criteria evaluated", ev.call_count == 1, f"calls={ev.call_count}")


def test_every_not_started_shape_is_refused():
    """One check per not-started shape named by the spec and task 2.1.

    The first gate only recognised `directive_never_started`. But agent.py
    returns three more strings BEFORE anything runs:

        agent.py:1065  f"FAILED dispatch_error {e}"     mod call raised
        agent.py:934   f"FAILED bad_directive {...}"    directive unparseable
        agent.py:959    "FAILED ASK_PLAYER no question given"
        plan_orchestrator.py:665  f"DISPATCH_ERROR: {e}"  dispatch_fn raised

    Each is a directive handed to nothing that came back. Under the old gate
    every one counted as a start, criteria were evaluated, and "holdings 0/0"
    could still mark the subtask complete - the 11-13 shape through another
    door. The last check pins the other side: a timeout DID start.
    """
    print("2e. every not-started shape is refused; a timeout is still a start")
    shapes = [
        ("FAILED STORE_ALL directive_never_started", False, "never appeared on mod"),
        ("FAILED STORE_ALL dispatch_error Connection refused", False, "mod call raised"),
        ("FAILED ASK_PLAYER bad_directive {'kind': 'ASK_PLAYER'}", False, "unparseable"),
        ("FAILED ASK_PLAYER no question given", False, "refused pre-dispatch"),
        ("DISPATCH_ERROR: Connection refused", False, "dispatch_fn raised"),
        ("FAILED MINE directive_timeout after 5m", True, "ran then failed"),
        ("COMPLETED GOTO {}", True, "ran"),
    ]
    for text, should_start, why in shapes:
        got = _dispatch_started(text)
        check(f"{'started' if should_start else 'NOT started'}: {why}",
              got is should_start, f"{text!r} -> {got}")

    # And end to end: a raised mod call must not let criteria pass the attempt.
    plan = _plan()
    _, dispatched, sub, ev = _run_step(
        plan, [{"kind": "STORE_ALL"}],
        lambda d: "FAILED STORE_ALL dispatch_error Connection refused",
        criteria="holdings 0/0 of minecraft:items")
    check("dispatch_error directive WAS sent", dispatched == ["STORE_ALL"],
          f"dispatched={dispatched}")
    check("dispatch_error: criteria not consulted", ev.call_count == 0,
          f"calls={ev.call_count}")
    check("dispatch_error: subtask not complete", sub.status != "complete",
          f"status={sub.status}")

    # And the genuine raise: a dispatch_fn that throws, so plan_orchestrator.py:663-665
    # (the except that builds DISPATCH_ERROR) is actually executed. The case above
    # only classifies a pre-formed string and would survive that except being gutted.
    def _boom(d):
        raise ConnectionRefusedError("Connection refused")

    _, dispatched, sub, ev = _run_step(
        _plan(), [{"kind": "STORE_ALL"}], _boom,
        criteria="holdings 0/0 of minecraft:items")
    check("raise: directive WAS sent", dispatched == ["STORE_ALL"],
          f"dispatched={dispatched}")
    check("raise: criteria not consulted", ev.call_count == 0,
          f"calls={ev.call_count}")
    check("raise: subtask not complete", sub.status != "complete",
          f"status={sub.status}")
    check("raise: error names DISPATCH_ERROR", "DISPATCH_ERROR" in (sub.error or ""),
          f"error={sub.error!r}")


def test_skill_exemption_is_exact_equality_not_prefix():
    """A name that merely STARTS WITH "SKILL" must not ride the exemption.

    This is the shape a prefix-match regression takes, and a bare invented kind
    (SEARCH_AND_STORE) cannot tell the two apart -- it is refused either way.
    1e therefore passes a prefix hole; this test does not. Verified against a
    real startswith('SKILL') mutant: 0 of the checks below survive it.

    SKILLETY is the second near-miss on that edge: a name that begins with
    SKILL but not with SKILL followed by a separator, so an exemption written
    as `startswith("SKILL_")` would still miss it.

    XSKILL / EVIL_SKILL pin the OTHER edge. Without them the test pins the left
    edge only, and an exemption written as `endswith("SKILL")` or
    `"SKILL" in kind` stays green while XSKILL dispatches and criteria are
    evaluated -- the same 11-13 shape from the far end of the string. Together
    the two families are what makes this a test of equality: no single-sided
    match satisfies both.
    """
    print("1g. SKILL exemption is exact equality, not prefix/suffix/substring")
    for name in ("SKILL_X", "SKILLETY", "XSKILL", "EVIL_SKILL"):
        # Directive side.
        _, dispatched, sub, ev = _run_step(
            _plan(), [{"kind": name}], lambda d: "COMPLETED %s {}" % name,
            criteria="holdings 0/0 of minecraft:items")
        check("%s: not dispatched" % name, dispatched == [],
              f"dispatched={dispatched}")
        check("%s: refused as unknown_kind" % name,
              (sub.error or "").startswith("unknown_kind:"), f"error={sub.error!r}")
        check("%s: criteria not consulted" % name, ev.call_count == 0,
              f"calls={ev.call_count}")

        # Flag side: the directive itself is a valid MINE, so only the flagged
        # near-miss kind can trigger the refusal.
        _, dispatched, sub, ev = _run_step(
            _plan(), [{"kind": "MINE", "target": "iron_ore"}],
            lambda d: "COMPLETED MINE {}",
            criteria="holdings 0/0 of minecraft:items",
            l2_flags=["unknown_kind:%s" % name])
        check("%s flagged: not dispatched" % name, dispatched == [],
              f"dispatched={dispatched}")
        check("%s flagged: refused as unknown_kind" % name,
              (sub.error or "").startswith("unknown_kind:"), f"error={sub.error!r}")


def main():
    for fn in (test_invented_kind_is_not_dispatched,
               test_skill_exemption_is_exact_equality_not_prefix,
               test_skill_is_not_refused_by_the_gate,
               test_skill_with_spec_reaches_refine,
               test_skill_synthesis_is_still_refused,
               test_alias_still_dispatches,
               test_known_kind_dispatches,
               test_l2mcp_flag_is_honoured,
               test_never_started_cannot_satisfy_a_true_criterion,
               test_one_started_directive_still_evaluates_criteria,
               test_zero_directive_attempt_is_unchanged,
               test_started_but_failed_still_evaluates,
               test_every_not_started_shape_is_refused):
        fn()
    print()
    if failures:
        print(f"FAILED ({failures} check(s))")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
