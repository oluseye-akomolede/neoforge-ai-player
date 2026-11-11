# Gate — M2 plan corrections at 1ccb38f

Rev: `1ccb38f`, branch `minecraft-wt-deepseek`, parent `771a2ef`
Range: `M2-PLAN.md` (+98/−12) and my own review file (+119, committed by the
builder alongside). Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS on corrections 1 and 2; correction 3 is applied correctly but
rests on a false premise that is blocking for the directive check.**

## Correction 1 (three times table) — applied, and correct

The table in §1 names tick cadence 2 s, `deadline_ms` 250 ms, snapshot bound
100 ms, and explains why the original sentence was wrong twice over. It cites
`TICK_DELAY` at `agent/config.py:89`; verified, `float(os.getenv("TICK_DELAY",
"2.0"))`. A correctly-disambiguated constant that three review rounds confused is
worth more than the fix it closes.

## Correction 2 (100 ms must be explicit) — applied, and better than asked

§4.4 now names `_post`'s 5 s default (`agent/api.py:33`, verified) and requires a
unit test that pins the script path to `SCRIPT_TIMEOUT = 0.1` and fails if the
argument is dropped. That is a mutation-resistant requirement rather than a
restatement, which is the right shape.

## Correction 3 — applied correctly, on a false premise (BLOCKING)

The count. My 36 was **wrong** and their **35 is right**: the frozenset at
`agent/l3_planner.py:204` holds 35 unique names. I reported 36 from a count that
included something outside the set. Recorded here so the number does not drift
again: **it is 35.**

Their fix goes further than my correction asked, and the reasoning is right — do
not hard-code a count that has drifted twice. But the replacement claim is false:

> `_VALID_DIRECTIVE_KINDS` … is the mod's `DirectiveType` enum.

It is not. `DirectiveType` (`src/main/java/.../brain/DirectiveType.java`) has
**37** members. The frozenset has 35. The difference:

- **In the mod enum, absent from the frozenset: `AREA_LOOT`, `SKILL`.**
- The frozenset's six excluded names — `EQUIP_ALL`, `EQUIP`, `DROP`,
  `VAULT_STORE`/`VAULT_WITHDRAW`, `PROVISION_TERMINAL`, `ASK_PLAYER` — are
  **not in the mod enum at all**, so the file's own comment ("agent-side
  conveniences, not mod directives") is accurate about them.
- The frozenset's exclusion rule is narrower than the enum: its comment says
  excluded kinds "would fail `SkillValidator`", i.e. this set is *the kinds a
  declarative skill leaf may use*, which is not *the kinds the mod accepts*.

Why it is blocking rather than cosmetic: M2's `api.do` resolves a script's
directive against whatever set the implementer reads, and §2 now says that set is
the enum. If `script_client.py` imports `_VALID_DIRECTIVE_KINDS` as instructed, a
script calling `api.do("AREA_LOOT")` or `api.do("SKILL")` is **refused although
the mod accepts it** — a false rejection of valid directives, discovered only by
a bot not doing what its script says. The reverse instruction (read the enum at
runtime) would need a Java-side source it cannot reach from Python.

**Fix:** state the rule, not the enum. §2 should say the accepted set is
`_VALID_DIRECTIVE_KINDS` **and that it is the skill-leaf subset of
`DirectiveType`, deliberately excluding `AREA_LOOT` and `SKILL`** — then say
which is intended for `api.do`. If scripts may use the full enum, the check needs
its own set; if they may only use skill-leaf kinds, the plan must say so, because
that is a real restriction on what a script can ask a bot to do.

This is the third distinct number for this set in two days (51, 36, 35) and the
first structural reason for the drift: two sets with different purposes were
being treated as one.

## What the rest of the corrections do well

- **§3.3's silence counter-case** is the sharpest thing in the diff. "Parity only
  proves the two paths agree *when both act*" is exactly the blind spot, and
  requiring *both* the absent chat line and the absent API call is right —
  asserting the chat line alone passes when the call goes out and fails.
- **§6's ConfigMap decision** records the reason (the §8 restart control mid-
  proof needs no rebuild) rather than merely the choice.
- The **§"Decided at review"** section turns three open questions into recorded
  decisions with rationale. Keep that pattern.

## Process note

My review file `REVIEW-M2-PLAN-771a2ef.md` was committed in `1ccb38f` alongside
the plan. It is my artefact and I would rather it sit in its own commit than
inside a plan correction — not a defect, but it means a `git revert 1ccb38f`
would take the review with the correction. Either is workable; naming it so the
choice is visible.
