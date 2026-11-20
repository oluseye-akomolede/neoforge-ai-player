# Review: snapshot registry ids, no dedup, nearest-K — `fb313cd`

**Rev:** `fb313cd` (on `c180797`, branch `minecraft-wt-deepseek`)
**Task:** 2.0 (snapshot ids/no-dedup/nearest-K), plus ticks on 1.1, 1.3, 1.6
**Verdict:** **PASS** — the code is right and independently verified. One residual
mismatch on the Python side is pre-existing, not introduced here, and is recorded
as N-1 rather than a hold.

---

## What was verified, by running it

**NearbyBlockIndexTest, run by me, not read from the builder's XML.**
`gradle 8.14` distribution invoked directly (the wrapper jar is absent as the lead
said), `GRADLE_OPTS=-Xmx2g` exported rather than passed as a `nice` argument,
`--max-workers=2`, `nice -n 19`, `--offline --rerun-tasks --no-build-cache`,
distribution `gradle-8.14/bin/gradle` from the wrapper dists cache (the wrapper
**jar** is absent, the distribution is not). The first attempt reported
`:test UP-TO-DATE` — a cached task that ran nothing — so the tally below is from
a forced run with `:test` actually executed (`BUILD SUCCESSFUL in 15s`,
XML timestamp `23:08`):

```
tests="8" skipped="0" failures="0" errors="0"
```

All eight named, including `theNearestChestIsKeptNotTheFirstInScanOrder`.

**The scan-order mutant, repeated by me.** Replaced `insert`'s distance-ordered
placement with plain append (first-K-in-scan-order, the `fb313cd^` behaviour),
keeping the K bound. Result: **8 tests, 1 failed**, and gradle's own report names
it:

```
NearbyBlockIndexTest > theNearestChestIsKeptNotTheFirstInScanOrder() FAILED
BUILD FAILED
```

Failure: `expected: <2> but was: <-5>` at `NearbyBlockIndexTest.java:57` — the
kept chest's `x`, i.e. the scan-order corner instead of the near one. No other
test reddened. File restored; `git diff --stat` empty.

*A note on reading this XML, because it bit me twice:* JUnit writes passing
testcases as self-closing `<testcase .../>`, so a regex pairing
`<testcase>(...)</testcase>` attaches the single `<failure>` block to the
**preceding passing testcase** (`airIsSkipped`). Read gradle's `> ... FAILED`
line, or parse the XML properly, before naming the failing test.

**The scenario values driven directly.** With chests at `(2,0,2)` (d²=8) and
`(-5,-5,-5)` (d²=75): K=1 keeps `(2,0,2)`; K=2 keeps both ordered nearest-first.
The `<=` tie-break keeps the earlier-scanned candidate on equal distance, which
is the scan-order tie-break the design specifies at `:202`.

---

## The lead's five questions

**(1) BotPlayer's cache really calls NearbyBlockIndex — yes, and the distance is
computed after the air test.** `BotPlayer.java:901-919`: `getNearbyBlocks` builds
`center = player.blockPosition()` and calls `NearbyBlockIndex.select` with the
three center coordinates. The candidate supplier returns `null` for
`state.isAir()` *before* constructing a `Block`, so `select` never ranks an air
cell — the air test genuinely precedes the distance computation, as `design.md`
requires. The cache radii are confirmed 5/16 at `BotPlayer.java:619-620`.

**(2) The payload shape matches the design.** `NearbyBlockIndex.java:82-84` emits
`{"id", "block", "position"}` — the registry id, the display name kept alongside
it, and `{x,y,z}` from `positionOf` (same shape as the existing `formatBlockPos`).
`HttpApiServer.java` passes `getCachedBlocks()` through untouched, so what the
index returns is exactly what the agent receives. See N-1 for the Python side.

**(3) Test counts — quoted above**, from a forced run.

**(4) Mutant — exactly one red, and it is the nearest-vs-scan-order test**, as the
builder claimed.

**(5) The task 1.3 rewrite is honest — accepted on the lead's terms.** The note
states the check as written cannot pass and says why: a sentence that *denies*
the 8/24 claim must contain the claim's words. I read all three hits in the
design myself rather than trusting the note: `design.md:27` denies ("the radii
the agent asks for are not the radii the bot gets"); `:161` and `:513` are
cost-table cell comparisons as part of radius-cubic arithmetic. None asserts 8/24
are served. The rewrite describes what it actually does — read each hit — which
is the standard the lead set.

---

## N-1 — the Python fixture asserts a shape the mod no longer emits (pre-existing)

`agent/test_snapshot.py:87` asserts `state["nearby"]["blocks"][0]["type"] ==
"minecraft:chest"`, and `:120` appends `{"type": "planted"}`. The real mod has
never emitted `type` for blocks — the design's §2 documents the pre-change shape
as `{block: <display name>, position}` — and now emits `id`. So this test is
pinned to a hand-written `_FakeApi` stub, not to the Java contract.

This is not introduced by `fb313cd` and does not block it: `_FakeApi` is a
recording stub and the assertion tests the stub's own default. But it means **no
Python test validates the real block-entry shape**, so a future change to `id` or
`position` naming would pass both suites. Worth a follow-up that drives a real
captured payload through `build_state`, which is the seam neither suite covers.

## N-2 — task 1.1's tick cites an `/egm-review` artefact that is not in this repo

Task 1.1 reads "`[x] design.md passes /egm-review as a document`". I read the tree
for such an artefact and found none: `grep -ril "egm-review"` across the repo
matches only this review file, and `reviews/` holds the six reviews I filed
(`371095c`, `5ae0372`, `a0146b0`, `b40f71b` and two earlier) and no egm output.

That is a scoped finding, not a claim that no review happened: `/egm-review` is a
skill the lead runs, and its output may live in the lead's session rather than a
committed file. **I am not disputing that the design was reviewed** — four design
reviews of mine exist and the outcome was fine. The point is that the tick is
the kind of claim that should be checkable from the tree, and this one is not. If
the egm output exists, commit it or name where it lives; otherwise the task should
cite the reviews that do.

---

## Not disputed

- The scan still visits the same 1331 cells; only the selection changed. No new
  allocation per cell beyond the `Block` record, which is created only for
  non-air cells.
- `NEARBY_BLOCKS_PER_ID = 2` is a named constant with its rationale in the
  Javadoc, matching the design's "nearest 2 per id".
- The `<=` tie-break is the specified one and is exercised by the K=2 replay.

Nothing built for deploy, pushed or deployed by this review. No `ollama-l3`
request, no pod exec, nothing in `ci`. The only tree mutated was a temporary
edit to `NearbyBlockIndex.java`, restored and verified clean.
