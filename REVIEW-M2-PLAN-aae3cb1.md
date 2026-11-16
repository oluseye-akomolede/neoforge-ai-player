# Gate — M2 plan two-sets fix at aae3cb1

Rev: `aae3cb1`, parent `1ccb38f`, `openspec/changes/coded-agents/M2-PLAN.md`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS on the set analysis; the decision it reaches is right for a
stronger reason than given, and unimplementable as written.** Two follow-ups,
one blocking for implementation rather than for the plan.

## The conflation fix is correct, and the table is the right instrument

`DirectiveType` 37 / `_VALID_DIRECTIVE_KINDS` 35, `AREA_LOOT` and `SKILL` in the
enum only, and the note that the frozenset's exclusion rule is "would fail
`SkillValidator`" rather than "the mod would reject it" — all verified:

- Enum members counted from `DirectiveType.java`: **37**.
- Frozenset at `l3_planner.py:204`: **35**, enumerable twice with the same result.
- Set difference: enum-only `{AREA_LOOT, SKILL}`, frozenset-only `{}`.

Naming the two sets by *purpose* rather than by size is what stops the count
moving again. Good.

## The decision is right, and the argument is stronger than the one given

They chose "`api.do` accepts the full enum (37)", reasoning that a script is not
a skill leaf and nothing validates a script that way. That is correct, and the
efficiency argument they did not make is decisive: the frozenset is consulted by
the **skill synthesiser** (`SkillValidator`, `SkillNode`), so the new rejection
already has a narrower set — `SCRIPT_DIRECTIVE_KINDS` — and no extra work is
created by the 37 choice. Build against the 37 *and* keep the narrow set for
synthesis.

## Follow-up 1 (blocking for implementation): Python cannot read the enum

> `script_client.py` builds its own `SCRIPT_DIRECTIVE_KINDS` from
> `DirectiveType`

There is no path for that. `DirectiveType` is a Java enum; the Python agent has
no import of it, no generated mirror, and no JSON export of it — `grep` for
`DirectiveType` across `*.py` finds one hit, a comment. So "builds its own set
from `DirectiveType`" means one of:

(a) a hand-maintained 37-name literal in Python — which reintroduces exactly the
    drift this table exists to stop, now with two copies to keep in sync;
(b) a build-time generation step from the Java source into Python — real work,
    and it has to fail loudly if the enum gains a member;
(c) the mod exposing its enum over HTTP — a new endpoint, which §1's own
    "measure before adding a mod endpoint" argues against.

The plan should pick one and say so. My recommendation is (b): generate the list
from `DirectiveType.java` at build time, with a test that fails when the generate
step's output is stale. That makes the "do not write the literal" instruction
hold in practice rather than in prose — as written, the plan forbids a literal
and then requires one.

## Follow-up 2: `SKILL` in `api.do` may be accepted but not satisfiable

The decision accepts all 37, and `SKILL` is one of them. But `SKILL`'s payload is
a skill id (`agent.py:3849` passes `target=sid`), and `SkillValidator:59` treats
`DirectiveType.SKILL` specially rather than as a leaf directive. So
`api.do("SKILL")` with a `target` naming a real skill is arguably valid, while
`api.do("SKILL")` with a target string is not — the validity depends on payload,
not on the kind alone. A 37-name set cannot express that.

This does not overturn the decision, but §2's refusal test should not include
`SKILL` as a plain accept case; it should test it with and without a resolvable
skill id, or the plan should scope `api.do` to non-`SKILL` kinds and say why.
Otherwise the plan ships a set that says "accepted" for a kind whose acceptance
depends on something the set cannot see.

## Non-blocking

My review file went into `aae3cb1` again alongside the plan. Same note as last
round; still not a defect, still worth deciding deliberately.
