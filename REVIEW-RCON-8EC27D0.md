# Review — rcon rotation, tracing guard

**Rev:** `8ec27d0` (parent `47bf396`), clean `git archive` export.
`openspec validate coded-agents --strict` → **valid**, rev printed in the same
command. Diff is plan-only, `+33` lines.
**Verdict: PASS on the hold; one residue worth one line.**

---

## 1. The hold is closed, and the guard is better than what I asked for

The `set -x` fix is at 1(ii) and repeated at 5(c), and the second placement is
the part I did not ask for and should have. Turning tracing off at the
assignment and back on before the *use* would leak at the use — the grep is fed
`$OLD`, and a traced re-expansion of it prints the value just as the assignment
did. Bounding the assignment alone is the fix that looks complete and isn't.

**Verified by running it, both polarities:**

| prior state | assignment region | leak in output | state after |
|---|---|---|---|
| tracing off | dark | none | still off |
| tracing on  | dark | none | **restored on** (`hxBc`) |

Restoring the *prior* state rather than forcing off is the detail I asked for
and the plan states the reason correctly: an operator who normally runs traced
would otherwise be silently detraced and keep believing they were.

I also checked three things the plan does not claim, all clean:
- Under `set -e`, `[ "$_xt" = on ] && set -x` when `_xt=off` does not kill the
  shell (a `&&` list's exit status is exempt). Both branches exit rc 0.
- The guard inside a pipeline: tracing state after the pipe is unchanged.
- `HISTFILE` restores correctly when it was previously set to a real path.

---

## 2. Residue — `HISTFILE` unset stays `/dev/null`

The guard remembers `_hf=${HISTFILE-}` and restores with
`[ -n "$_hf" ] && HISTFILE=$_hf`. When `HISTFILE` was **originally unset**, that
restore is skipped and leaves `HISTFILE=/dev/null` in place:

```
$ bash -c 'unset HISTFILE; …guard…; [ -z "${HISTFILE+x}" ] && echo UNSET || echo "SET [$HISTFILE]"'
SET [/dev/null]
```

So after the rotation the operator's shell stops recording history for the rest
of the session — silently, and it is the same defect the guard exists to
prevent: assuming a prior state instead of restoring it. Low severity (no
credential leak; history is *suppressed*, not written), but a one-line fix and
in the same class as the `set +x` assumption they already fixed.

**Fix:** distinguish unset from empty and restore the *presence*:
`if [ -n "${HISTFILE+x}" ]; then HISTFILE=$_hf; else unset HISTFILE; fi`

Same shape applies to `_xt`/`_hf` themselves — they are left in the session
afterwards. Harmless, but the plan's own "clear the variable and close the
session" sentence suggests it cares about residue; naming these two costs a
clause.

---

## 3. What I am still not verifying

Unchanged from my last review and now stated once: every cluster fact —
`/image/scripts/start-configuration:87-88`, the file mtimes, the pod start time,
the 1168-file scan, the four-way fingerprint match. None reachable from this
seat. I reviewed the guard's behaviour (which I can run) and the plan's
internal consistency (which I can read). The builder's account of the
measurements is theirs, and they accepted that split explicitly, which is the
right way to leave it.

---

## 4. Scope

Nothing rotated, executed, built or deployed by me. No credential value printed;
the sample base64 `U0VDUkVUVkFMVUU=` is a locally generated dummy in this review,
not from the cluster, and I am confident of that because I generated it in the
test above.
