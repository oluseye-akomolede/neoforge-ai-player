# Review: host-api-count-seven N-1 fix (`4cae197`)

**Verdict: PASS.** The cosmetic note is taken correctly, the failure message now
names the right cause, and the new classification holds under six mutations I drove
against it. One latent code smell (L-1), not demonstrated on any real input, not a
blocker.

- Repo: `neoforge-ai-player`, branch `spec-host-api-seven`
- Reviewed rev: `4cae197` (parent `61df265`)
- Row: `qitem-20261126232139-8d95311f469a9252`
- Prior review: `reviews/2026-11-26-host-api-count-seven-l1-61df265.md`

Every claim below was produced by me from the revs named, not taken from the row body.

## Scope

`4cae197` changes one file, `check_cites.py`, +27/-6. The spec text is **byte-identical**
to `61df265`: `git diff --quiet 61df265 4cae197 -- '.../specs/' .../proposal.md .../tasks.md`
is clean. So the scenario table, the zero-"six" check, the `fleet.js:166` sentence and
both strict validates all carry forward unchanged from the `61df265` review — I did not
re-derive text that did not move.

Instrument note: my first scope check used `git diff --quiet 61df265 4cae197 -- openspec/`,
which includes the script, and printed "DELTA CHANGED". That was my check being wrong,
not the delta moving. Re-ran scoped to the spec/proposal/tasks paths.

## The change

The presence set holds exact `(file, start, end)` tuples, so a stale CHECKS entry and a
prose-moved range were indistinguishable to it — both were reported as "stale CHECKS
entry". That message misled the reader about which end had drifted, which is the same
species of error that ran through this change's earlier rounds.

The fix compares a missing entry against the nearest cite in the same file (threshold 8
lines): near → `PROSE moved`, with the nearest cite printed; nothing near → `STALE entry`.
The two causes are now reported as two causes, and `moved` is tallied separately in the
summary rather than folded into `vanished`.

## Driven, not read

Scratch worktree detached at `4cae197`; checker run from the repo root against
`~/minecraft/agent-script-runner` at `b48c4ad`. Worktree removed afterwards, spec restored
byte-identical.

Baseline: **13 claims, all clean, rc=0**, and the caveat line ("this binds code to these
claims, not the prose to them. The sentences still need reading.") is intact.

| Case | Mutation | Reported | rc |
|---|---|---|---|
| A | prose `342-346` → `342-343` | PROSE moved, nearest `342-343` | 1 |
| B | entry file `binding.js:436` → `engine.js:436` | STALE entry | 1 |
| C | `459-466` → `466` (range collapsed) | PROSE moved, nearest `466-466` | 1 |
| D | `436` → `900` (same file, 464 apart) | STALE entry | 1 |
| E | `436` → `460` (24 apart, inside another range) | STALE entry | 1 |
| F | add `342-343` alongside `342-346` | ungoverned cite | 1 |

All six fail closed. B and E are the ones that matter for the heuristic's honesty: a
file-level test could not tell B from A (binding.js is cited elsewhere), and E confirms
the 8-line threshold does not reach across to the `459-466` range 24 lines away. The
builder's commit message says they hit both of those while developing; the behaviour is
real and I reproduced it independently.

F is worth one line: a duplicated cite does not confuse the classifier, it becomes an
*ungoverned* cite and fails loudly. Nothing slipped through.

Instrument note: my first runs failed 13/13 because I passed a runner path that does not
exist (`minecraft-wt-qwen/agent-script-runner`) — the repo is at `~/minecraft/agent-script-runner`.
A uniform total failure is the signature of a bad argument, not a bad script; I checked the
path before reporting anything. A usage-message run also exited 0 without arguments, so the
`rc` had to be read from `PIPESTATUS` on a real invocation.

## L-1 — nearest is chosen by one metric and tested by another (latent)

```python
near = sorted((p for p in present if p[0] == fname),
              key=lambda p: min(abs(p[1] - end), abs(start - p[2])))
close = near[0] if near and min(abs(near[0][1] - end),
                                abs(start - near[0][2])) <= 8 else None
```

The sort key and the closeness test are the same expression here, so they agree — I could
not construct a misidentification. But `key` sorts on the raw difference while the comment
describes "adjacent", and if either expression is ever edited independently the nearest
candidate could be rejected while a farther one goes untested. The real delta's cites are
spread (`96`, `111-118`, `192-195`, `214-216`, `327-496`, `342-346`, `436`, `459-466` in
binding.js), so no input today exposes it.

**Not a defect I demonstrated, and not a request.** Recorded because this script's whole
value is being trusted on failure, and a classifier whose two halves could disagree is
worth a comment saying why they are the same expression on purpose.

## Validate

Both run from a worktree detached at `4cae197`, rc read directly:

- `openspec validate host-api-count-seven --strict` → valid, rc=0
- `openspec validate bot-coded-agents --strict` → rc=0

## Summary

N-1 closed: an entry that is no longer in the prose and a range the prose moved now produce
different messages, verified across six mutations, all failing closed. The script remains a
manual aid (unwired — no reference to `check_cites.py` outside itself) that binds code to
claim, not claim to prose, and says so on its own green line. Nothing blocks archive.
