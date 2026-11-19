# Review: 619da8b - M3-2 step (a) spec rev 3

**Verdict: NOT YET, one finding (R1), narrow.** C1 is properly closed and the
provenance design is the right call. Doc-only, 3 files. openspec --strict rc=0.

## C1 closed - verified, not taken

The contradiction is gone and the distinction is carried consistently:

  spec.md:131  condition 2 - "No HAND-WRITTEN script ... A script this agent
               itself wrote and bound in this process is NOT hand-written for
               this purpose"
  spec.md:108  Scenario "A passing dry tick rebinds a PREVIOUSLY WRITTEN script",
               GIVEN "a bot whose bound script THIS agent wrote and bound in
               this process" -> THEN "condition 2 holds ... latch is reset"
  spec.md:176  Scenario "A HAND-WRITTEN script is not displaced"

The rebind scenario can now pass, which was the whole point: the reset is
reachable in the case it exists for. :160's "not displaced" now scopes to
hand-written, so it no longer contradicts :108. Your audit of the 24
displacement-ish hits is the right method and I could not find a survivor.

Citations printed at this rev: agent.py:3027-3035 is _bound_script_path and
:3037 is def _get_script_tick - your correction is right. bindings.get(:3027),
hold :1330-1333, dispatch :2901-2904 all correct.

## On your question: is the provenance field too much for this change?

No. It is the minimum that makes (b) evaluable, and the alternative is worse.
You are right that "no hand-written script bound" cannot be read from
bindings.json: I confirmed `bindings = json.load(...)` at :3013 yields a flat
name->filename map and _bound_script_path treats the value only as a filename
(:3027-3035). (b) as I literally wrote it was untestable - that was my error,
not yours, and your fix is the correct one. Keeping it in-process needs no
schema change and uses a fact the agent already has at bind time.

## R1 - "in process" is undefined across a restart, and the script outlives it

This is the one thing to add before step (b) implements it.

The script is stored where bindings.json lives, under the scripts dir
(_bound_script_path, agent.py:3011-3023 reads
`os.path.join(scripts_dir, "bindings.json")`, mounting a ConfigMap). That
survives a pod restart and is shared. The provenance record is "in process"
(spec.md:154), which does NOT.

So after any restart:
  1. pre-restart, the agent wrote scriptX, bound it, recorded "I put scriptX here"
  2. restart. bindings.json still maps this bot -> scriptX. The provenance
     record is gone.
  3. the fresh process reads scriptX and has no in-memory claim on it
  4. condition 2 asks "did this agent put the bound script here, or did a human?"
     and the only answer available is "a human"

Agent-written scripts therefore become indistinguishable from hand-written ones
on every restart, and the rebind is permanently disabled for them: exactly the
unreachable-reset defect C1 was about, re-entering through the process lifetime
instead of through the condition wording. A bot that wrote its own script on
Monday can never replace it on Tuesday.

Not asking for a schema field in bindings.json - you are right to avoid that.
The cheapest resolutions, your choice:
  (a) say provenance is deliberately process-scoped and state the consequence:
      after a restart an agent-written script is treated as hand-written and is
      not displaced. That is a defensible safety stance (a restart is a
      deliberate deployment boundary) - but it must be WRITTEN, because a later
      implementer will otherwise read "in process" as a bug and fix it into a
      bindings.json field.
  (b) let the agent claim a script it can prove it wrote - e.g. a marker inside
      the stored artefact itself, which travels with it and needs no bindings
      schema. Then a restart re-derives provenance from the script's own bytes.
(b) keeps the mechanism reachable across restarts; (a) is simpler and safe if
you accept "restart freezes the current script". Either is fine. What is not
fine is leaving "in process" to mean whichever the implementer assumes.

## Everything else
Rate-budget, memory, rebind-in-requirement and per-bot condition all still
correct at this rev. Vacuity note honoured. No other finding.
