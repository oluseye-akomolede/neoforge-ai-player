# Review — M2 step 4, eighth gate (`c859de4`)

**Row:** `qitem-20261111124635-9baa2a708ca95045`
**Verdict: HOLD on one line. Everything else in this rev passes, and both named
fixes are correct — the sweep did not reach the second instance of the same error.**

Reviewed in a clean `git archive c859de4` export. `openspec validate coded-agents
--strict` → **"Change 'coded-agents' is valid", rc=0**, rev `c859de4` printed beside
it. `51d1aaa..c859de4` touches `M2-PLAN.md` only, so the code passed at `85f6809`
and the 82-OK suite still carry — no re-run owed.

---

## 1. Both named holds are fixed — PASS

**Row 2** (`:1154`) now reads *dispatch present, `not executed:` absent*, with the
success return marked **not** in the agent log. Right fix, and the parenthetical
sends the operator to the right place instead of leaving them hunting.

**Line 712** now cites `85f6809`. Correct.

---

## 2. HOLD — line 1229 repeats the error the sweep was meant to catch

`:1229`, in the note explaining row 1's revision:

> **Row 1's revision is computed, not read.** `823920fd7277b98b` is
> `sha256(agent/scripts/scout.js)[:16]` at **`d75f30b`** Recompute it against the
> image that actually ships; if the script changed, this value changes and a stale
> one in this table is the whole finding.

Measured again at every rev:

| rev | `sha256(scout.js)[:16]` |
|---|---|
| `d75f30b` | `7fdbad9076381f43` |
| `85f6809` | `823920fd7277b98b` |
| `c859de4` | `823920fd7277b98b` |

This is the identical sentence defect fixed at 712 in this same commit — the value
from `85f6809` attached to the rev `d75f30b` — surviving two lines below a note
whose entire subject is that the revision is *computed, not read*. The sentence
that tells the operator where the number comes from states a rev where the number
is different.

**Why the sweep missed it, precisely.** The sweep you describe checked
*value-consistency*: "the revision citations are all 823920fd at 85f6809 or later."
Run literally, that test passes here — `d75f30b` was never registered as "or later".
A value sweep cannot find a bad *pairing* unless it hashes each cited rev, which is
`for r in <revs>; do git show $r:path | sha256sum; done`. The four-comment counts
you grepped for `COMPLETED` are sound for their purpose; the revision check needed
a different tool.

**Fix:** `d75f30b` → `85f6809` at line 1229. One word.

**Also worth a look while you are there:** the sentence has no full stop between
"at `d75f30b`" and "Recompute it against", so it reads as one run-on. Cosmetic, but
this is the line an operator quotes when they record the run.

---

## 3. What I checked and found correct

- **Row 2** — observable, and the remaining clauses are sufficient.
- **Line 712** — `85f6809`, correct.
- **Rows 1, 3, 4, 5, 6** — all name surfaces that emit what they claim. Row 1's
  `823920fd7277b98b` is correct for the shipping rev.
- **The four `COMPLETED` hits** (`:1162`, `:1182`, `:1183`, `:1222`) — three are
  the removal rationale and one is the orchestrator's return contract. **None
  claims agent-log visibility.** Your sweep was right about this.
- **Strict validation at the rev** — valid, rc=0, rev printed in the same command.
- **Diff is plan-only** — no code change since the `85f6809` pass.

---

## 4. Not verified by me

- Cluster facts (namespace, pod label, `PROFILES_DIR` on the live pod, deployed
  image provenance). No cluster access from this seat.
- The initContainer manifest: written, not applied, not exercised.
- The runner end-to-end. The `dispatch:`/`COMPLETED` observation is from the agent
  suites, which is the surface the plan's rows name.

Nothing built, nothing pushed, nothing deployed.

| item | verdict |
|---|---|
| Row 2 `COMPLETED` clause | **PASS** — deleted, correct basis |
| Line 712 rev | **PASS** — now `85f6809` |
| Line 1229 rev | **HOLD** — same error, `823920fd…` with `d75f30b` |
| `COMPLETED` sweep (4 hits) | **PASS** — none claims agent-log visibility |
| Revision sweep | **incomplete** — checked values, not pairings |
| `openspec validate --strict` at `c859de4` | **PASS** — valid, rc=0 |
| Code unchanged since `85f6809` | **PASS** — plan-only diff |
