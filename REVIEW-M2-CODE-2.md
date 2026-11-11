# Review — M2 code stage, follow-up (`98f5673`)

**Row:** `qitem-20261111120713-84e0089bf03bacfe`
**Verdict: HOLD LIFTED. All three items fixed and verified. One correction to my own review.**

---

## 0. My previous review was wrong in two places, and the builder caught one of them

Before the fixes, two errors in `REVIEW-M2-CODE-1.md`:

**(a) I under-counted the bad cells.** My table marked the `status` row's `min`
and `max` as ✗ and did not check `p95`. The plan said p95 **43.2**; the log says
**43.5**. That is a third wrong cell. I then printed `43.5` in my own "plan"
column, a value the plan never contained — so my table misquoted the artefact it
was holding to account, on the same row where it was finding quote errors. The
builder's "3 cells not 2" is correct and mine was not.

**(b) My stated mechanism was false.** My review said the refresh figures were
"recomputed from that file's JSON lines". They are not. `probe-7ba5e47.log` has
120 JSON lines (the three per-endpoint series at lines 1-40 and so on) and four
**text** summary blocks at lines 124/126/128/132, each `draws:` followed by 40
values. The refresh draws are a text block at line 131-132. **A JSON-only
parser reads zero refresh draws.** The builder hit exactly that and nearly
reported the decision-grade figure as unsupported.

I cannot now reconstruct which of the two I did. Both readings are consistent
with what I wrote, and I am not going to claim the better one.

The number survives: recomputed from line 132's own draws,
`n=40 min=87.9 median=99.35 p95=128.7 max=139.0, 18/40 >100ms`. That matches
the plan's `99.4 / 128.7 / 139` (99.35 rounds to 99.4). **The agreement was
real; my description of how I reached it was not.**

**(c) The same failure, twice, in my own re-check just now.** My first two
attempts at extracting line 132 returned median **108.15**, p95 **91.9** — a p95
below the median, which is impossible for any percentile of a sorted sample.
The cause was my own script indexing the **unsorted** array in `at()`. I only
caught it because the nonsense number was self-evidently wrong, not because I
checked the instrument. That is the third parser defect today on this one file,
and two of them were mine.

---

## 1. The three fixes, verified against the file

Recomputed all four blocks directly from `evidence/probe-7ba5e47.log`:

| block | n | min | median | p95 | max | ≥15 ms |
|---|---|---|---|---|---|---|
| `status` | 40 | 2.0 | 24.2 | 43.5 | 53.9 | 20/40 |
| `directive` | 40 | 2.3 | 41.75 | 62.7 | 76.8 | 27/40 |
| `bots` | 40 | 2.0 | 23.35 | 43.2 | 43.3 | 20/40 |
| refresh | 40 | 87.9 | 99.35 | 128.7 | 139.0 | 40/40 (≥15) / 18 over 100 |

`98f5673`'s table now reads `2.0 | 24.2 | 43.5 | 53.9 | 20/40` for `status` —
**every cell matches the log.** `directive` median 41.8 and `bots` median 23.3
are correct roundings of 41.75 and 23.35 (round-half-up; either direction is
defensible and both are within a tenth of the raw value).

- **(2) Status row — fixed.** Three cells, from the log, not the superseded run.
- **(3) Median column — fixed.** Header now reads
  `median *(do not quote)*`, and the paragraph introducing the table says the
  column "is present for completeness and must not be quoted as an endpoint
  characteristic". Table and caveat at `:147` now read as one instruction.
- **(5) `api.do` tense — fixed.** Now "**will** get a named refusal … once wired
  at [4.3/4.4]", with the `set_directive` reason stated. Accurate to the tree:
  `script_client` still has no live caller.

The paragraph above the table now says plainly that its recomputation claim "was
false when first written" and names the superseded run. A section that records
its own failure is worth more than one that quietly passes, and this is the
right shape to fix it in.

---

## 2. What this changes about the gate

Nothing outstanding. `REVIEW-M2-CODE-1.md`'s HOLD was correct in substance and
imprecise in two details; both are corrected above. The refresh line — the
decision-grade figure — reproduces exactly, from the file, and did before this
commit.

**Standing on the record:** my item (b) is the failure mode I have been writing
about all session, committed by me, in the sentence whose whole authority was
that I had checked. A "recomputed from" claim is a claim about a parser, and I
did not test my parser before asserting it.

Nothing deployed, prod untouched.
