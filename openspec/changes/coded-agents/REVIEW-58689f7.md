# Review: 58689f7 - M3-2 step (a) spec rev 4 (R1 resolved)

**Verdict: PASS.** The accepted cost is acceptable for the owner. Doc-only,
3 files, `openspec validate ai-written-scripts --strict` rc=0 and
`show --json` deltaCount 3, both run from `git archive 58689f7`, not a worktree.

Row responded on: qitem-20261120005150-b22bc52d8503ab66.

## The competing write claims - both partly right, resolved

Two statements were in play and neither was fully accurate:

- my 6820541 note said there was **no write path at all** in the agent;
- the builder said the agent has **no write path for script source**;
- the lead's row pointed at `agent.py:1623` as the only file write, writing plans.

Printed at `58689f7`, all three resolve:

  :1623   `_plan_store.write(plan)`
  :3006   `scripts_dir = (_os.getenv("SCRIPTS_DIR") or "").strip()`
  :3011   `bindings_path = _os.path.join(scripts_dir, "bindings.json")`
  :3035   `return _os.path.join(scripts_dir, name)`

A grep for `open(...,"w")` / `.write(` / `os.makedirs` / `shutil.copy` / `os.rename`
over the whole of `agent.py` at this rev returns exactly one real write:
`:1623`. `plan_store.write` (`agent/plan_store.py:40-46`) serialises a `Plan`
to JSON via tmp+replace - plan data, never JS source. The bindings file is
opened read-only (`:3013`, no mode). So:

- the builder's claim is CORRECT: there is no write path to script source;
- the lead's pointer is CORRECT and was the useful one: `:1623` is a real file
  write, so my "no write path at all" was too strong and I withdraw it.

This matters because it is the premise for ruling out option (b). An in-artefact
provenance marker needs a write to the artefact; no such path exists; building
one is a storage design and belongs to a later step. The builder did not dodge
(b) - it was unavailable.

## R1 closed

spec.md:166-188 states provenance is deliberately process-scoped, says why in
the storage model, and states the consequence as a MUST: after a restart an
agent-written script is indistinguishable from a hand-written one and is not
displaced. tasks.md:70-76 (2.8) repeats the reasoning for an implementer and
tells them explicitly NOT to "fix" it into a `bindings.json` field or an
in-file marker. Scenario "A restart freezes the script an agent wrote"
(spec.md:204-209) makes it testable rather than prose-only.

All ten citations in the new text verified by printing them at this rev:
:3027 `name = bindings.get(self.name)`, :1330 `self._script_hold = {`,
:1333 `}`, :2901 `hold = getattr(self, "_script_hold", None)`,
:2904 `return SCRIPT_HELD`, plus the four above. No stale numbers.

## The judgment the lead asked for: is the cost acceptable?

**Yes, and it is proportionate rather than merely tolerable.** Three reasons,
each checked rather than assumed:

1. **The bot does not stall.** A restart freezes *replacement*, not running. The
   bound script keeps driving the bot (spec.md:211-215 - it keeps driving until
   it fails by its own outcome classes or is unbound). So the failure mode is a
   stale-but-working script, not an idle bot and not a silent wrong action.
2. **The escape hatch is ordinary.** Unbinding is a `bindings.json` edit in a
   ConfigMap - the same class of action as any deployment change, performed by a
   human who is already the one authorising it. The code's own docstring
   describes this file as "deliberately dull... read once, no state"
   (agent.py:2987-2994), so the mechanism is not being bent to carry provenance.
3. **The alternative is worse, and this is the decisive point.** The rejected
   design trusts an authorship claim the process cannot verify. That fails
   *silently in the dangerous direction*: a stale script would silently outlive
   the intent that produced it, which is exactly the class of defect
   (silent wrong action) that 9.4 and the M3-1g hold work exist to eliminate.
   Freezing until a human acts fails *visibly and safely*.

So the trade is "an occasional human ConfigMap edit after a restart" against
"silent continuation of a script nobody can prove is current". That is the right
way round for the owner's stated goal.

## Residual, non-blocking

The accepted cost is asymmetric in one way worth a later row, not this change:
a bot that authored several scripts over time loses all provenance at once on
restart, so a restart mid-iteration can freeze a bot on a script the agent had
already decided to replace. Still safe (it runs, it is visible, a human can
unbind), but if step (b) introduces any agent write path, provenance should be
revisited at that point rather than staying frozen by 2.8. Task 2.8 as written
would tell that implementer not to - which is correct for THIS change and should
be revisited when the storage design lands. Not a finding against this rev.
