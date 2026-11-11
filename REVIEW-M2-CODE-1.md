# Review — M2 code stage (conditions 3 and 4)

**Row:** `qitem-20261111120713-84e0089bf03bacfe`
**Verdict: HOLD on one defect in the plan table; everything else PASSES.**

Revs reviewed:
- `agent-script-runner`: `fb92891`, `41bc354`, `7ba5e47`, `e5595e0`
- `neoforge-ai-player`: `f6b859a`, `104a756`, `83fbab8`

I ran the tests and recomputed every figure in the plan's §1 table from the
committed draws. Nothing below is taken from the handoff prose.

---

## 1. The median fix is correct, and it was my finding

`7ba5e47` changes median from `at(0.5)` (nearest-rank) to the mean of the two
middle values at even n. I verified by executing the function, not by reading it:

| series | median | old `at(0.5)` |
|---|---|---|
| 20×4.6 + 20×42.1 (n=40) | **23.4** | 4.6 |
| [1,2,3,4] (n=4, even) | 2.5 | — |
| [1,2,3,4,5] (n=5, odd) | 3 | — |
| 1..40 linear, p95 | **38** (index 37) | — |

On a bimodal series nearest-rank reports the lower-middle draw — 4.6 where the
true median is 23.35. That is a misleadingly fast number on the statistic the
100 ms-bound decision rests on. **The fix is right and the diagnosis in the
commit message is right.**

The commit also credits it as the check I asked for (a raw block must reproduce
its own row) applied to their own output. That is the correct provenance: the
defect was in a probe I had already reviewed and passed.

---

## 2. HOLD — the plan's §1 table does not reproduce from the log it cites

`M2-PLAN.md:116-121` says every row "reproduces from the printed draw series",
and names `agent-script-runner/evidence/probe-7ba5e47.log` as the source.

Recomputed from the JSON lines in that exact file:

| row | plan | log | |
|---|---|---|---|
| `status` min | **1.4** | **2.0** | ✗ |
| `status` max | **61.5** | **53.9** | ✗ |
| `status` median | 24.2 | 24.2 | ✓ |
| `status` ≥15ms | 20/40 | 20/40 | ✓ |
| `directive` median | 41.7 | 41.8 | ~ (rounding) |
| `bots` median | 23.4 | 23.3 | ~ (rounding) |
| refresh median / p95 / max | 99.4 / 128.7 / 139 | 99.3 / 128.7 / 139.0 | ✓ |

**`min 1.4` and `max 61.5` appear in neither committed log.** The two logs
give status min/max as 2.0/53.9 (`7ba5e47`) and 1.5/91.1 (`41bc354`). The
plan's row is a third set of numbers that no committed artefact supports.

This is the same defect the section was written to fix, one commit later: a
summary block that its own raw data contradicts. The section's own words —
"verified by recomputing each summary from its own draws, not by eye" — are
precisely what fails on this row.

**The fix is small:** take the four `status` cells from the log (2.0 / 24.2 /
43.5 / 53.9 / 20-40) or say which run produced 1.4/61.5 and commit that log.

**What is not affected:** the refresh line is the decision-grade figure and it
reproduces exactly (n=40, 87.9 / 99.3 / 128.7 / 139.0). The 300 ms bound and
per-tick cache stand on their own.

---

## 3. The bimodal reading is right and the plan is honest about its limits

Every endpoint shows the same two modes, ~2–6 ms or ~42–44 ms, nothing between.
The log's timestamps show the mechanism: slow draws are ~43 ms apart and each
fast draw lands ~3 ms after one — a periodic stall, not per-endpoint cost.

The caveat at `:129-133` is the most valuable writing in the diff: a bimodal
series has no stable median, so "do not quote a per-endpoint median as a
characteristic of that endpoint; quote the two modes and the ≥15 ms count." That
is correct, and it is a rule the table above it does not yet obey (it prints a
per-endpoint median column). Not a defect — the caveat governs use — but worth
resolving so the table and its warning read as one instruction.

---

## 4. Directive names — PASS

- `104a756` tests: **11/11 pass** (`python3 -m unittest`, stdlib only, as
  claimed — pytest is not installed here and is not needed).
- `DIRECTIVE_KINDS` is hand-copied, so I diffed it against the Java enum:
  **37 vs 37, set difference empty in both directions.** Not a matching count —
  a matching membership.
- Behaviour probed directly: `mine`→`MINE`; `DROP`, `EQUIP_ALL`, `BOGUS` all
  raise `UnknownDirective` naming the directive and the set size.
- The two mod facts in the test docstring are true: `HttpApiServer.java:1341`
  upper-cases before `valueOf`, so case was already accepted end-to-end and the
  plan's original "lowercase would fail" premise was false. The real defect —
  an unknown name throwing inside the handler as a nameless 500 — is the right
  thing to fix.

---

## 5. One claim in the plan overstates the present

`M2-PLAN.md:368`: "A script calling `api.do("DROP",…)` gets a named refusal
rather than a silent no-op."

That is not true today. `script_client` is imported by nothing outside its own
tests (`grep -rn` over `agent/` returns no callers), and `set_directive` at
`api.py:428` builds `{"type": directive_type}` with no guard. The plan states
the deferral clearly two paragraphs later ("added at step 1 but WIRED at tasks
4.3/4.4"), so this is one unqualified sentence disagreeing with the rest of the
section, not a hidden gap.

**Fix:** tense. "…**will get** a named refusal once wired at 4.3/4.4."

---

## Summary

| item | verdict |
|---|---|
| `7ba5e47` median fix | PASS — correct, empirically verified |
| `41bc354` / `e5595e0` probe + logs | PASS — log reproduces; refresh exact |
| §1 table `status` row (1.4 / 61.5) | **HOLD — unsupported by the cited log** |
| §1 bimodal re-reading + caveat | PASS — correct and well-qualified |
| `104a756` directive names | PASS — 11/11, membership-exact vs enum |
| `f6b859a` / `83fbab8` plan edits | PASS apart from §5 below |
| `:368` present-tense wiring claim | MINOR — change tense |

Nothing deployed, prod untouched. I did not run the probe myself (no cluster
access from this seat); I recomputed its statistics from the committed draws.
