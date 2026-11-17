# Review: ea6500f — M2-PLAN §8.4 rewrite (docs only)

Reviewed at `ea6500f` in `~/minecraft/neoforge-ai-player`. One file,
`openspec/changes/coded-agents/M2-PLAN.md`, +70/−20. Read-only throughout;
no workload started, stopped, paused or resumed.

## Verdict: PASS with two findings

The rewrite is honest, it is sourced, and its live-baseline table matches the
cluster field for field. Both findings are about statements that are *narrower*
than the evidence supports, not about anything false that would mislead a run.

---

## Q1 — C2b row against the §8.4.1 pass rule: PASS, and the rule is applied exactly

The row claims, from the 2026-11-13 11:16:14Z capture:
48 accepts 11:14:17–11:16:13Z; 48 `fallback_timeout: read timeout` lines
11:14:17.61–11:16:13.82Z; 0 `dispatch:`; one `connect refused` at 11:14:15.20Z.

Checked against the three void conditions in §8.4.1's C2b row:

| Void condition | Evidence | Result |
|---|---|---|
| any `connect refused:` **after** the first accept | the only refused line is 11:14:15.20Z, ~1.9 s **before** the first accept 11:14:17Z | not triggered |
| a timeout with **no** accept recorded | 48 accepts recorded | not triggered |
| a fallback line **before** the first accept | first timeout 11:14:17.61Z, after the 11:14:17Z accept | not triggered |

The row also states the refused line "precedes the first accept, i.e. C2a's
window" — that is the correct reading, and it is the inference the pass rule
requires. **Verdict: the C2b row meets §8.4.1.**

Limit I must state plainly: the 11-13 capture is not in the repository, so I am
testing the row's own numbers against the rule, not re-deriving them from the
raw log. The arithmetic is internally consistent (48 accepts, 48 timeouts, one
per accept, first accept 11:14:17Z ↔ first timeout 11:14:17.61Z). If the lead
still holds the capture, a byte-level re-read would close that gap; I could not.

## Q2 — C2a claim "evidence read 11:04:43Z, before the ~11:11Z listener exec": right, and the correction is well framed

This is the strongest edit in the commit. The original §8.4 said "nothing in this
section has run"; the rewrite records C2a as PASS *and* records that a builder
exec at ~11:11Z perturbed the same pod. Putting the evidence timestamp (11:04:43Z)
against the perturbation (~11:11Z) is what makes the PASS defensible rather than
quietly contaminated, and the row explicitly bounds the damage (one stray
`read timeout` line, outside the evidence window).

**Verdict: the claim is right as written.** Its form — "before the exec, so the
window is clean" — is the correct way to present a contaminated pod.

## Q3 — C1 'owed': agreed

The 2026-11-11 13:2xZ no-script run dispatched `WIDE_SEARCH`, not `STORE_ALL`.
§8.3.4 Run 1 and the §8.4.1 C1 row both require the *absence* of a
`[Scout/script] dispatch:` line. A run that dispatched a different goal is not
a weaker C1; it is a different arm and proves nothing about the no-bindings
branch. **Agreed: it does not stand in for Run 1.** Marking C1 OWED is correct.

## Q4 — §8.4.2 / §8.4.3 / §8.4.9 against live: all four verified, one row stale-label

Measured 2026-11-17 10:2xZ via `ssh controlplane kubectl` (read-only; no exec,
no secret read):

| §8.4.3 claim | live value | verdict |
|---|---|---|
| `spec.paused` unset | unset | ✓ |
| strategy `Recreate` | `Recreate` | ✓ |
| pod `…-fc9f559cb-q49qp` | `aibot-agent-test-fc9f559cb-q49qp`, Running, 0 restarts, 40h | ✓ |
| image `2914fb85…` | `agent@sha256:2914fb85ff22…80083` | ✓ |
| runner `e07a90c5…` | `agent-script-runner@sha256:e07a90c56537…` | ✓ |
| `scout.js` `1824967e200dab94` / 5852 B | identical | ✓ |
| `bindings.json` `10cef1b830853225` / 26 B | identical | ✓ |
| template `restartedAt` 2026-11-13T05:16:47Z + `m2-step4: step1-inert` | both present, values identical | ✓ |

I hashed the ConfigMap `data` in-place and printed only 16-char prefixes and
byte counts; `scout.js` was never written to a terminal or a file.

§8.4.2's premise is exactly right and live: paused unset, `Recreate`, and the
inert `m2-step4` annotation still on the template. The new rule against changing
the template during a run is the correct replacement, and it is *better* than
the old pause rule because it names the actual hazard (an SSA that owns and
deletes undeclared template annotations) instead of a state that no longer holds.

§8.4.9's rollback paragraph is correctly fenced by the update block above it.

## Q5 — surviving pause/resume/rollout instructions: none reachable for C1

Every remaining `rollout pause` / `rollout resume` / `spec.paused=true` string
in §8.4 sits in one of:

- §8.4.4 (C2a), now headed **(EXECUTED 2026-11-13: PASS; kept as the record)**
- §8.4.5 / §8.4.5.1 (C2b), likewise labelled executed
- §8.4.9's **"Restore the pause state too"** paragraph, which the 2026-11-17
  block immediately above it explicitly scopes: *"The paragraph below applied to
  the C2 arms on 2026-11-13."*
- §8.4.2's replacement text, which *forbids* rather than instructs

The head of §8.4 also states plainly: *"Their paused-Deployment steps describe
the state on 2026-11-13 and do not apply to C1."*

**Verdict: nothing in §8.4 tells C1 to pause, resume, or `rollout restart`.**

---

## Findings

**F1 (minor, §8.4.9).** The "Restore the pause state too" paragraph keeps the
imperative mood — *"`kubectl -n minecraft-test rollout pause …`"* — and is
fenced only by the italic note above it. The fence is unambiguous to a careful
reader and the paragraph is needed as the C2 record, so this is not a defect to
act on now. But it is the one string in §8.4 that could still be followed by
someone skimming for "what do I run at the end", and on the now-unpaused
Deployment it would *pause* a Deployment the plan says must stay unpaused.
Suggestion, for whenever that section is next touched: make the paragraph's
first words the scope ("**C2 arms only, 2026-11-13:** …"), in the same style as
the 4.4 fix in `adee29a`. No action requested for this commit.

**F2 (minor, §8.4.3 baseline table).** The table is labelled *"measured by the
lead 2026-11-17 10:2xZ"*. Every value in it is still correct at 10:2xZ **and**
at the time of this review, so nothing is wrong. The note only becomes an issue
because §8.4.3 then says *"Re-measure every row immediately before C1"* — which
is exactly right, and which the next reader should trust over the table itself.
No change needed; recorded so the table is not quoted as C1-time evidence.

## Note on scope

I did not and cannot run C1, and did not touch the Deployment, the pod, the
runner, or the ConfigMap. All cluster access was `get`/`json`, read-only, test
namespace only.
