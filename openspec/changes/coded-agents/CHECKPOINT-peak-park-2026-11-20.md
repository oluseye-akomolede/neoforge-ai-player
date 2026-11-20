# Reviewer checkpoint — peak-park 2026-11-20 00:52Z (resumes 04:00Z)

Seat: minecraft-reviewer@minecraft. Worktree: ~/minecraft-wt-qwen/neoforge-ai-player,
branch `minecraft-wt-qwen`. Working tree clean at `8fef6f2`.

## IN FLIGHT — finish this first on resume

`58689f7` (M3-2 step (a) spec rev 4). Builder sent it at 19:14Z. I had NOT
answered when the park landed. Nothing is owed by me yet, but the builder is
blocked waiting on a verdict.

What the rev does: chooses resolution (a) for my R1 — provenance is deliberately
process-scoped, so after a restart an agent-written script MUST be treated as
hand-written and is not displaced. Cost is named in the requirement. Adds a
restart-freezes-the-script scenario and tasks.md 2.8 telling later implementers
NOT to "fix" it into a bindings.json field or an in-file marker.

Builder's reason for (a) over (b): the agent has NO write path for script source
anywhere. `SCRIPTS_DIR` at agent.py:3006; the only accesses are reading
bindings.json (:3011) and joining the resolved filename (:3035). So my option (b)
(marker inside the stored artefact) would need a write path that does not exist
in this change. I started verifying this claim when the park landed — IT IS
UNVERIFIED. Verify at `58689f7` before accepting.

Answer they asked for: whether the accepted cost ("a bot that wrote its own
script before a restart cannot replace it after one until a human unbinds it")
is too high to ship. My lean when interrupted: it is acceptable, because a
restart is a real deployment boundary and the alternative — trusting an
authorship claim the process cannot verify — is worse. But that lean rests on
the unverified no-write-path claim above.

## Standing rules for the resume

- Their numbers are stale roughly one time in three this session. PRINT EVERY
  CITATION at the rev under review. Do not accept any l.NNN from a message.
- Spec-only revs: validate from `git archive <rev>`, never from this worktree —
  this branch is far behind `ship-ca27-harness` on agent.py (was 25 commits
  behind at one point) and reading the working file gave me wrong line numbers
  and a retraction I had to make in writing.
- openspec rc: read through PIPESTATUS; a pipe returns the footer's status.
- Node suites need NODE_OPTIONS heap bounds, never `ulimit -v` (kills the WASM
  parser). test_agent_script_branch must run from inside agent/, else 45
  AttributeErrors from the stub-bootstrap import order.

## Not mine

The lead's live TEST run of the M3-1g hold fix (`acf051e`/`8a7f10f`) was still
the open gate when this parked; I claimed no live evidence for it. If it landed,
the M3-2 work may need a re-read against whatever it showed.
