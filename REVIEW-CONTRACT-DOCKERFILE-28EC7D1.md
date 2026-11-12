# Review — 28ec7d1 (both corrections from 2ef8180 landed)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-12
Verdict: **PASS.** One cosmetic defect in the new evidence file; it does not
touch the shape and should not hold the rebuild.

This commit exists to change the image, so it is the one that ships. I measured
it on a clean `git archive 28ec7d1` export, not in the builder's tree.

`openspec validate coded-agents --strict` → `Change 'coded-agents' is valid`,
run **inside the `28ec7d1` export** (evidence file present, Dockerfile fix
present, verified in the same command). My worktree HEAD is `2ef8180`, which does
not contain this rev — a first validation there returned valid about the wrong
tree, so it is recorded here rather than trusted.

---

## 1. CORRECTION 1 — the three namings, verified 13 -> 0

The builder is right that my figure was incomplete. My review counted
`test_*.py` (9) + `tests/` (2) = 11 and missed a third naming, `*_test.py` at top
level. Enumerated on the export before running anything:

```
./agent/rl_reward_test.py
./agent/task_d_fixes_test.py
./agent/test_*.py            (9 files)
./agent/tests/*.py           (2 files)
./agent/testing/run_tests.py (harness)
```

14 test-shaped paths, 13 of them tests plus the harness — their number, derived
here rather than taken from them.

Ran their committed line in the `WORKDIR` context where `COPY . .` has run:

```
Dockerfile:37  RUN rm -rf ./tests && rm -f ./test_*.py ./*_test.py
before: 13 test files    after: 0
survivor: ./testing/run_tests.py
```

**The survivor-claim checked, not assumed.** "Nothing imports it" is a claim
about the tree, so I grepped for importers with a positive control: at
`b1ad67e` (a tree that still holds the removed files) the only import-shaped
hit was a docstring in `test_scripts_configmap.py` that *mentions*
`test_scout_script.py` in prose. No module imports `run_tests`, `rl_reward_test`,
`task_d_fixes_test`, or `tests.*`. The harness is also self-contained — its only
importer is its own sibling `testing/harness.py`, which is the function it calls,
not a consumer of the entry point. Leaving it deliberately is the right call and
the commit says why.

`agent.py` still parses on the post-`rm` tree.

**Worth recording, because it is the second time today:** the builder reports
they first wrote "15 -> 0" into the message from a `find '*test*.py'` that
counted the harness, caught it against an explicit `ls`, and amended before
pushing. That is the same defect the commit fixes — a claimed count and an
artefact with nothing comparing them — caught one level up, before it shipped.
The first version of the message restated it; the committed version does not.

---

## 2. CORRECTION 2 — evidence now exists, and it is a real capture

`evidence/m2-run2/get-directive-shapes.txt` is in the tree at this rev, with pod,
image digest, method and timestamp in the header. I could not re-measure it:
**`kubectl` is not present on this seat** (no binary in `PATH`, `/usr/local/bin`,
`/snap/bin` or `~/bin`, no wrapper). So TEST is unreachable from here and I did
not pretend otherwise — the capture is the builder's, as its header says.

What I *can* check is whether the captured shapes are consistent with every
consumer in the tree, and they are:

- Idle shape `{"progress":{"phase":"idle"},"self_preservation":"ok","state":"Standing by"}`
  — matches the contract's recorded shape at `contract-v1.md:213` and the guard's
  comment at `scout.js:47`.
- Busy shape — `progress.phase` is present and non-idle, `directive.status` is
  `ACTIVE`, and `state` is the human string, exactly as `scout.js:50-53`
  describes.
- Both are **objects, never null** — which is the whole point of the HOLD this
  closes. A `progress`-is-a-number contract, or a `task`-is-null idle contract,
  would each have made `scout.js` hold forever or act on an idle bot.

The contract's citation at `:226` now points at a file a reader can open. That
was the defect; it is closed.

**The fixture provenance also improves.** The six review rounds of
fixture-vs-producer gap that ran through this change all came from fixtures
written from what the consumer expects. `test_scout_script.py` at this rev
carries the real shapes (`IDLE_DIRECTIVE`, `BUSY_DIRECTIVE`) and its docstring
names the exact failure mode it is guarding against. That is the right direction.

---

## 3. FINDING (cosmetic, does not hold the rebuild) — the file disagrees with itself on the directive id

The evidence file's own text and its own captured JSON differ:

```
:19  ## BUSY — a WIDE_SEARCH directive in flight (id 14)
:22  {"directive": {"id": 15, ...}, ...}
```

The builder's message also says `id 15`. The captured JSON is the artefact; the
heading is prose about it. One of them is stale.

**Why it does not hold the rebuild:** the id is not load-bearing. No consumer
reads it, the shape is identical either way, and the guard keys on
`progress.phase`. The correct fix is one character in line 19 (or, if 14 was
correct and the JSON is from a later directive, a note saying so). Either way
the capture's value as a shape record is unaffected.

I am flagging it rather than waving it through because it is the *same class*
one more time, at the smallest possible scale: an assertion beside an artefact,
nothing comparing them. The build should not wait on it; the builder should fix
it in the next commit that touches this file, and I would like the amended file
to state which of 14/15 the captured response actually carried, since that is
the only way a reader can tell which line was wrong.

---

## 4. What I did not verify

- Every cluster fact. `kubectl` is absent on this seat; I could not reach the
  pod, the running agent, or TEST. The evidence file is the builder's capture and
  I reviewed its internal consistency, not its truth.
- I did not build the image. The `rm` is simulated on `git archive` output in a
  shell, faithful to the globs and the `WORKDIR` but not a `docker build`.
- The suite. The builder reports 101 tests green apart from a pre-existing
  dashboard/uvicorn stage; I did not reproduce it, and note that the removal
  deletes test files, so the suite's own count after this change is a
  *post-removal* number, not a measure of what the tests cover.

---

## Verdict

**PASS.** Correction 1 is correct and is better than my finding — it found the
third naming I missed. Correction 2 closes the citation defect with a real
capture and a method that would have caught a constructed fixture. The only
outstanding item (§3, the id in the evidence heading) is cosmetic and does not
change what ships.

**The rebuild can proceed.** This is the image I reviewed.
