# Review — rotation plan re-review

Commit `ff32d68` (parent `bfd544e`). Plan only; nothing has run.

**Verdict: PASS on both required changes. One MINOR correction to a stated
measurement, not blocking. No secret value appears in this review.**

---

## 1. Required change 1 — APPLIED, and correctly

The load-bearing label moved from 4.1 to 4.3/4.4, and the *reason* travelled
with it:

- `tasks.md:47-51` — 4.1 restated as "the mod rejects the old key", scoped to
  exactly what it measures, with the explicit line: **"A green 4.1 beside red
  4.3/4.4 is a failed rotation."**
- `tasks.md:52-62` — 4.3 and 4.4 both marked **LOAD-BEARING**, with the reason:
  a client on the stale key gets a 401 from the mod that is indistinguishable,
  from the mod's side, from correct retirement.
- `proposal.md` — the section heading changed from *"Why old-key-gets-401 is the
  right post-condition"* to *"Why old-key-gets-401 is necessary but not
  sufficient"*. The original claim that the mod "is the only authority on
  whether the rotation took" is replaced by exactly the right statement of its
  limits.

**This is the better form of the fix.** My required change was to move a label;
they also removed the false sentence from the proposal and left a positive
statement of what 4.1 *does* establish, so a reader does not swing from
"4.1 proves everything" to "4.1 proves nothing". The claim now has a floor as
well as a ceiling.

I swept the change for other instances rather than checking only the two files
in the diff: the only surviving count references are "three consumers"
(`proposal.md:18`, `tasks.md:93`) and "18 keys" (`proposal.md:46`), both still
true. All three `902a001fdc05` references are consistent — 3.5 verifies the new
fingerprint differs from it, 5.2 verifies it returns on rollback.

## 2. Required change 2 — APPLIED, and better than asked

I asked for the game-server cost to be stated. They stated it, and where I said
"I could not verify whether the mod saves on SIGTERM", they **went and checked**:

- `preStop`: `timeout 30 rcon-cli stop` → wait ≤180 s for the Server thread →
  TERM → 30 s → KILL. A normal stop saves the world. **No data loss.** This is
  the single most important fact in 3.6 and it is now established rather than
  assumed.
- `terminationGracePeriodSeconds: 300`, strategy `Recreate`.
- Restart order (mod, then both clients) and the resulting 401 window are stated
  in **both** 3.6 and the proposal, with the note that a red `l2-mcp` flag
  during the window is expected. That is precisely the confusion I was worried
  about, pre-empted.
- 4.5 now requires the **measured** downtime on the row, not the estimate.

## 3. MINOR — a measured figure attached to the wrong span

`tasks.md:60-61` and `proposal.md:84-85` both say:

> PodScheduled `04:33:55Z` → container started `04:34:15Z` → Ready `04:38:11Z`,
> i.e. **3 m 56 s from schedule to Ready**.

Arithmetic:

| span | duration |
|---|---|
| PodScheduled → container started | 20 s |
| container started → Ready | 236 s = **3 m 56 s** |
| **PodScheduled → Ready** | **256 s = 4 m 16 s** |

3 m 56 s is the **container-started → Ready** span — the boot time. The phrase
says "from schedule to Ready", which is 4 m 16 s. The scheduling 20 s is
excluded from the number and included in the description.

This is minor and the fix is one of two words ("from container start", or
change the figure to 4 m 16 s). It is worth correcting because 3.6 exists to
bound operator downtime, and this is the number someone will plan around. The
plan's own instruction — "do not carry this estimate forward as a measurement" —
is well aimed at exactly this failure.

The stop bound is stated correctly: ≤30 s stop + ≤180 s thread wait + ≤30 s TERM
= 240 s, which is a genuine worst case for the stop half.

## 4. The inventory result

New evidence, reported this message rather than in the commit. I could not
verify it: there is no `kubectl` in this seat, so this is my reading of their
method, not a reproduction.

**The method is the right one and it is what makes the result worth having:**
sha256 fingerprint of the decoded value, never printing a value, sweeping
Secrets **and** ConfigMaps, then all Deployments' literal env values, then every
namespace in the cluster. The final sweep is the one that matters — it is what
turns "I found two in the test namespace" into "and there is no third one
anywhere else".

Two things I want on the row:

1. **The 13 → 14 correction is the encouraging part**, not a worry. It is what a
   real enumeration does when re-run, and it is reported rather than quietly
   amended. The corrected figure does not propagate anywhere else, because no
   document ever cited it.
2. **The deployment-environment sweep's zero needs its positive control stated
   on the row.** "All 10 Deployments, literal env values, zero hits" is a claim
   about a query, and a query that cannot match returns zero identically to a
   world that is clean. The test namespace sweep returned 2 hits and the
   all-namespace sweep returned the same 2, which is evidence the method can see
   values — but neither demonstrates it can see a *Deployment's inline
   `env.value`*. If one of the ten had held the key, would the sweep have found
   it? One sentence on how that was confirmed would close it.

## 5. Verified

- `openspec validate rotate-test-mod-api-key --strict` → **valid, rc=0**, at
  `ff32d68`, rev printed by the command in the same invocation.
- The `skip_specs` INFO line still reads correctly: a rotation changes no
  capability, so zero deltas is the right answer rather than a missing delta.
- Both `HttpApiServer.java` claims that the plan rests on were verified in my
  previous review at `:58-62` and `:148` and are unchanged by this commit.

## 6. Scope

- Plan only: nothing deployed, prod untouched, no cluster writes by me.
- The inventory, the live pod timings and the preStop hook are the builder's
  readings. No `kubectl` in this seat.
- The consumer replica counts remain unverified by me; the manifests are not in
  these repos.
