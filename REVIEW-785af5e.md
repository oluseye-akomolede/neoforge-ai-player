# Review 785af5e — guards read commands, not prose

**Verdict: PASS. F7, F8 and F9 are all genuinely closed — I reproduced every
mutant myself from a clean clone of the branch. Two forward-looking guard gaps
below are recorded, not blocking; the shipped script is correct as written.**

## F7 closed — verified by reproduction, not by reading the claim

`actionable_commands()` takes the payload of each `echo "..."`, skips payloads
whose first non-space char is `#`, and keeps those containing kubectl. Both
guards now test per-command.

Mutant (client-side apply-pipe restored on the exec create at :164):

    rc=1
    FAIL (client-side apply): ... --dry-run=client -o yaml | kubectl apply -f -
    A ~600 KB ConfigMap exceeds the 262144 B last-applied annotation cap ...

That is the guard firing on the exact bug it was dead against at 1adfc7f. Real.

## F8 closed

Deleting the whole delete-line (with a comment left behind saying to delete, and
again with no comment at all) both give rc=1, "never deletes them (checked
executable commands only)". The comment no longer satisfies the guard.

## F9 closed

The `items` comment now states the stem-keyed overwrite rather than "scores plan
cases twice". Corrected.

## Suites (counted by the runner, not by grepping)

113 eval tests (config 13, extract 33, run 19, run_declined 3, scorers 28,
sysprompt 17), 0 failures. Matches the builder's figure exactly.

## G1 (recorded, not blocking) — the delete guard checks SOME delete, not the right ones

`deletes = [c for c in kubectl if "delete configmap" in c]` then `if ... not
deletes`. That is a non-emptiness test: it never compares which names are
deleted against which are created.

  mutant: delete line narrowed to only `$NAME` (drops $REBUILD_NAME $CODE_NAME)
  -> rc=0

Consequence: a delete that covers only one of the three maps passes, and the
other two retain stale keys through the create. Low stakes today (the shipped
line deletes all three), but the guard's message says "delete-then-create" while
the check only says "deletes something".

## G2 (recorded, not blocking) — order is not checked, and the message says it is

Same code, no ordering comparison between `deletes` and `creates`.

  mutant: delete line moved AFTER the three creates (all names correct)
  -> rc=0

Consequence: delete-after-create fails every create with AlreadyExists on a
re-run, and on a first run silently deletes the maps it just made. The guard's
own FAIL text advertises "delete-then-create" as the remedy, so the invariant is
named in the code and not enforced by it.

Both G1/G2 are the same shape as F7 one level down: the check verifies that the
required verbs are PRESENT rather than that the required sequence is CORRECT.
Cheap to close — parse the three creates and one delete into ordered
(name, verb) pairs and assert set-equality plus delete-before-create. Worth
doing because the failure they miss is silent (green suite, stale keys on
controlplane), which is the class this whole row has been about.

## Still unproven (agreed, and correctly stated by the builder)

Guards prove things about the text the operator pastes; nothing proves
controlplane accepts it. That limit is real and is distinct from F7, which was a
local bug and was fixable locally. The builder now draws that line correctly.
