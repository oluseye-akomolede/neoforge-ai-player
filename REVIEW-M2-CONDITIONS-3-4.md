# Review — M2 lead conditions 3 and 4

Commits under review: `fb92891` (agent-script-runner, probe), `104a756` and
`f6b859a` (neoforge-ai-player). Reviewed at `f6b859ae07bd15c1fc258f5192cd54d844cc2a51`.

**Verdict: PASS on the decision and on condition 4. PASS WITH ONE REQUIRED
CORRECTION on the §1 table, which is a presentation defect in an otherwise
honest correction.**

---

## 1. The correction itself is the right call, and it is uncomfortable for me

`f6b859a` says the re-run of the committed probe contradicts §1 and marks the
original cells `~~superseded~~` rather than deleting them. That is the correct
form and it is the harder form to write, because the builder is contradicting a
section I have now passed three times (`08804f1`, `d18582e`, `afb7acc`).

The substance:

- `/status` was reported "consistently fast" at 3.0 ms. Re-run: **bimodal**,
  median 40.4, 20/40 samples ≥15 ms.
- `/bots` was reported "deterministic ~42 ms". Re-run: **bimodal**, with 1.5/2.2
  and 2.6 ms samples adjacent to 42.2/42.4.
- Two-cause story ("hop for `/directive`, separate deterministic cost for
  `/bots`") **does not survive**; one shared ~42 ms stall on all three endpoints
  is the likelier reading.

My own review history is entangled here. I spent several rounds establishing that
`/bots` at ~42 ms was *deterministic and unexplained* — including withdrawing a
contention theory of my own when the builder's interleaving test appeared to rule
it out. The re-run shows my "unexplained but deterministic" characterisation was
itself an artefact of a small sample. The builder was not correcting a mistake I
made; the original measurement was theirs — but I endorsed the deterministic
reading repeatedly and did not ask whether n was large enough for the claim. That
is the durable lesson: "deterministic" is a claim about the tail of a
distribution, and it needs more than 14 interleaved samples to establish.

## 2. Required correction: the raw `status` draws do not match their own row

The re-run table says:

| `status` | 2.1 | 40.4 | 43.8 | 53.7 | 20/40 | bimodal |
|---|---|---|---|---|---|---|

The text introducing the raw draws says:

> Raw `status` draws: `5.7 3.6 42.7 40.4 3.1 42.5 53.7 10.2 3.4 42.6 40.6 2.1
> 42.2 2.1 42.7 2.7 42.7 3.7 41.9 2.3`.

That list is **20 values**, and rendered from it:

```
n        : 20
>=15 ms  : 10      (row says 20/40)
median   : 25.3    (row says 40.4)
min/max  : 2.1 / 53.7   (row says 2.1 / 53.7 — these two agree)
```

So the draws are consistent with being the first half of a 40-sample run, and the
table is consistent with the full 40. **The defect is that the sentence does not
say so.** Read literally it offers a 20-sample list as the evidence for a 40-row
and a 40.4 median, and every reader who checks it will get 10/20 and 25.3 and
conclude one of the two is wrong.

Fix is one clause: either label it "first 20 of 40" or print all 40. Do not
change the table — the table is right.

This matters more than a typo because the whole commit's value is "the numbers
are re-derivable". A raw block that fails to reproduce its own summary inverts
that.

## 3. The probe is sound; three properties checked

`agent-script-runner/scripts/probe-snapshot-latency.mjs` at `fb92891`:

- **Monotonic clock** (`process.hrtime.bigint()`), not `Date.now()`.
- **Full body read** at `:77` before stopping the clock — a headers-only timing
  would miss the transfer being measured.
- **One discarded warm-up per endpoint** (`:94`), so `min` is not a cold-start
  claim.
- **A failed sample throws** (`:81`) rather than being timed as a fast one.
- **Key read from env, never printed**, and refuses to run without it (`:32`).
- The four-call refresh issues the same endpoints in the same order a planner
  iteration would, measured sequentially.

One small accuracy note, not blocking: `stats()` computes
`p95 = s[floor(0.95*n)]`, which for n=40 is index 38 — the 39th of 40, nearer
p97.5 than p95. It does not affect the decision (that rests on median and max),
but a p95 column that is really p97.5 should not be quoted as p95 where the
number is load-bearing.

## 4. Condition 4: correct, tested, and the set is exact

`104a756` adds `agent/script_client.py` with `DIRECTIVE_KINDS` and a normalise
plus refuse pair. Checked rather than accepted:

- **`DIRECTIVE_KINDS` == `DirectiveType`, member for member.** Extracted both
  sides programmatically: 37 in the enum body, 37 in the frozenset, zero members
  in either direction's difference. Not just the count matching — the failure
  mode there is a right count with a wrong member.
- **The 35/37 distinction is preserved and is now correct in both places.** The
  comment states this is the enum, not the skill-leaf set, and the test pins it.
- **Both underlying facts are true on this revision:**
  `HttpApiServer.java:1341` really is `.get("type").getAsString().toUpperCase()`
  before `DirectiveType.valueOf`, so lowercase already works — the earlier plan
  claim that it "would fail there" was false and is now corrected in both the
  plan and §3.2.
- **Tests: 11/11 pass** (`python3 -m unittest tests.test_directive_names`).
  Stdlib only, as claimed; pytest is not installed here and is not needed.

The decision to split — normalise case, refuse unknown — is right for the reason
given: they are different failure modes. Case is *already forgiven* by the mod, so
refusing it would invent a rejection that the system does not have; an unknown
name genuinely throws inside the handler and surfaces as a nameless 500, so
refusing it locally is a strict improvement.

## 5. `script_client` is imported nowhere — stated, not hidden

`grep -rn "script_client\|DIRECTIVE_KINDS" agent/ --include=*.py` outside the
module and its test returns **nothing**. Nothing in `agent.py` calls it.

This is the same shape as the `load_profile` defect from `4bf3ce3` — correct code
that nothing executes — but it is **not the same defect**, because here it is
intentional: tasks 4.3 and 4.4 are still open `[ ]`, so the wiring belongs to
step 2. The distinction matters and should be written down: a module added ahead
of its call site is fine; a module cited *as the live path* is not. `104a756`'s
message describes it as "agent-side directive dispatch", which reads as live.
One clause in the plan saying "added at step 1, wired at 4.3/4.4" would remove
the ambiguity for the next reader.

## 6. Scope

- I did **not** re-run the probe. The re-run at 11:44Z is the builder's, as a
  bounded Job in `minecraft-test`; it is reproducible from `fb92891` but has not
  been reproduced by me.
- I did **not** verify cluster state — no `kubectl` in this seat.
- The refresh numbers (median 94.9, p95 129, max 133.6 against a 100 ms bound) I
  did not independently measure; they are internally consistent with the
  per-endpoint rows (four calls, roughly half at ~42 ms, gives a median in the
  mid-90s).

**What I am confident in:** the decision is unaffected and correct; the table's
conclusion (all three bimodal, one shared cause) is better supported than the
reading it replaces; the frozenset is exact; the 11 tests pass; the two mod facts
are true. The one thing to fix is the raw-draw label.
