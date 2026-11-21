# Review: 6bceb29 — F-3 follow-ups (F-1 corrected, reader codes named, naming pinned)

Rev: 6bceb29 (neoforge-ai-player, ship-ca27-harness)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21
Related: 15b7d7f (review a709d51); F-1/F-2/naming filed there.

## Verdict: PASS, with F-4 (phantom rev cited in shipped files)

All three follow-ups land correctly, and the builder's restatement of my F-1 is
stronger than what I wrote. But the commit surfaces an unrelated defect that I
filed as F-4.

## The three follow-ups

**F-1 — the builder is right and I under-called it.** I filed it as "minor prose:
.length throws, not undefined". The builder sharpened it into the correct claim:
the two wrong readings are *different failure modes*, quiet-versus-raise, and a
test that only proves "proposes nothing" does not prove the guard is safe on the
other shape. I checked this in node rather than accepting the wording:

  wrapper.length            -> undefined,  wrapper.length > 0 -> false  (silent, never fires)
  list.inventory            -> undefined
  list.inventory.length     -> TypeError: Cannot read properties of undefined (reading 'length')
  Array.isArray-guarded     -> [] and never reaches the throw

So the shipped guard survives only because of the Array.isArray test, exactly as
the new prose says. My "minor" framing was the weaker reading; the spec now says
the stronger and correct one. Good correction.

**F-2 — the reader-error codes are named and the line cites resolve.** Verified
at 6bceb29: `:70` the exception-type branch, `:103` `wrapped-value-not-a-list`,
`:106` `unexpected-shape`, `:119` the `mobs`/`entities` mapping. All four exact.

**Naming — the mobs/entities paragraph is accurate.** It states the three live
names (endpoint and wrapper key `entities`, snapshot key `mobs`, script accessor
`look.entities`). `snapshot.py:119` maps them as described. This is the clause I
asked for and it reads correctly.

`openspec validate coded-agents --strict` rc=0. Suites at the rev:
`test_snapshot` + `test_scout_script` -> Ran 53, OK.

## F-4: a commit that does not exist is cited as the fix, in shipped files

`b9edb63` is not an object in this repository:

  $ git cat-file -t b9edb63
  fatal: Not a valid object name b9edb63

It is cited as "when _obs started unwrapping at the source" in three places,
two of which are shipped artefacts:

- `agent/scripts/scout.js:91` — "When _obs started unwrapping at the source
  (b9edb63) that read became undefined and this guard stored nothing, permanently"
- `deploy/agent-scripts.yaml:125` — the same sentence, in the ConfigMap copy
- `agent/test_snapshot.py:125` — "# b9edb63: live, state.nearby.blocks held
  {"blocks": [...]} unchanged"

The actual unwrap is `a81d5d19` — the commit under review when this was the row
title's rev, before I found it did not exist and the work was committed. The
phantom sha came in with `a81d5d19` and has been carried since.

Why this matters beyond tidiness: these are the comments a future implementer
reads to understand *why* the guard is shaped as it is. They name a sha they will
fail to find, and the natural inference from a missing sha is that the fix was
squashed, lost, or reverted — which is precisely the doubt this change exists to
settle. The `git log` blame correctly attributes the unwrap to `a81d5d19`.

Fix: replace `b9edb63` with `a81d5d19` in all three places, regenerate the
ConfigMap with `scripts/gen-scripts-cm.py` (the drift test will red otherwise),
and re-run. Mechanical, low risk.

I did not edit these myself: they are the builder's files and the correction
touches a shipped script comment, which should go through the same drift test as
any other scout.js edit.

## Instrument note (mine)

My first pass grepped `agent/scripts/` in a worktree that predated `a81d5d19`
and returned nothing for `state.inventory` — a false zero that would have looked
like "scripts do not read the inventory at all". The positive control caught it:
`scout.js:109` demonstrably reads `state.inventory`. I checked out 6bceb29 and
re-ran, and the greps then returned the expected hits. Reporting the zero would
have been the instrument, not the world.
