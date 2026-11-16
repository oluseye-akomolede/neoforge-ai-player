# Review — rotation plan, third pass

Commit `6915b2a` (parent `ff32d68`). Plan only; nothing has run.

**Verdict: PASS. Both my minor and my (a) are closed. The builder also corrected
a blind spot in *my* sweep, which is the more valuable half of this round.
No secret value appears in this review.**

---

## 1. The downtime figure — corrected, and the correction is instructive

All three intervals are now given, in both `tasks.md:61-66` and
`proposal.md:96-100`:

| span | duration |
|---|---|
| schedule → container start | 20 s |
| container start → Ready | 236 s = 3 m 56 s |
| **schedule → Ready** | **256 s = 4 m 16 s** |

`sched` → `Ready` = 20 + 236 = 256 s. The plan says to plan downtime around
**4 m 16 s** and states plainly why: *"3 m 56 s is boot alone; quoting it as
schedule-to-Ready understates the outage by the 20 s the scheduler spends
first."* That is not a footnote patched onto a wrong number — it explains the
error mode so a reader who sees 3 m 56 s elsewhere (their own earlier message,
the pod events) knows which span it belongs to.

## 2. The (a) positive control — built, and it controls the right thing

`proposal.md:47-50` now records:

> **Positive control:** the same query sees 50 inline env literals and correctly
> matches a value known to be present (`NODE_OPTIONS` on `agent-script-runner`).
> Without that control a zero is indistinguishable from a query that cannot
> match at all, and neither of the other two sweeps exercises this path.

This is the correct control, and the reason is worth stating: the zero was never
in doubt as an *absence of hits*. The doubt was whether the extraction over
`.spec.template.spec.containers[].env[].value` reaches inline literals at all —
the other two sweeps read Secret/ConfigMap data, which is a different path. The
control shows 50 literals extracted and one matched, so the path is live and the
zero is an absence rather than a blind query.

**One residual, which I do not think needs action:** the control value
(`NODE_OPTIONS`) is a plain string, while the target is a 40-char secret. A
query that fingerprinted correctly would behave the same for both, so this
demonstrates the extraction path, which is the part that was at risk. I note it
so that if the sweep is ever extended to encoded forms, the control is
re-examined rather than assumed to cover them.

## 3. The builder corrected my sweep, and it was a real defect in it

I reported that no stale "13" survived, based on `grep -rn "13 \|14 "`. The
builder found `proposal.md:42` still saying **"Ten Secrets and three
ConfigMaps"** — the count spelled out in prose, so a digit grep could not match
it.

That is the exact failure I have been charging to others all session: **a query
that cannot match returns the same result as a clean world.** My sweep was not
evidence. Re-run with `\b(thirteen|fourteen|13|14)\b` and with the word forms
included, the only remaining hits are the corrected line at `proposal.md:44-45`,
which records both passes deliberately:

> 1. **14** Secrets and ConfigMaps in `minecraft-test` — 2 hits. (An earlier
>    pass counted 13; a second pass found one more object. The corrected count
>    is 14.)

Keeping both passes rather than only the final figure is right, and it is the
same choice they made with the `102 → 119` suite count: a reader can see why the
number moved, which is what makes a corrected figure trustworthy.

I have added "sweep word forms as well as digits" to my own checklist. It is the
second time this session a number I was looking for was spelled out where I was
grepping for a digit.

## 4. Verified

- `openspec validate rotate-test-mod-api-key --strict` → **valid, rc=0**, at
  `6915b2a`, rev printed by the command in the same invocation.
- `skip_specs` INFO still correct: a rotation changes no capability.
- Arithmetic checked independently: 20 + 236 = 256 s = 4 m 16 s.
- The two `HttpApiServer.java` claims the plan rests on (`:58-62` startup read,
  `:148` empty-key-opens) are unchanged by this commit and were verified at
  `bfd544e`.

## 5. Scope

- Plan only. Nothing deployed, prod untouched, no cluster writes by me.
- The inventory sweeps, the pod timings and the preStop hook are the builder's
  readings; I have no `kubectl` in this seat and did not reproduce them.
- The consumer replica counts remain unverified by me — the manifests are not in
  these repos.

**State of the plan:** every required change from my two earlier reviews is
applied. The remaining gate is the lead's OK to begin §2. Nothing in this review
blocks that.
