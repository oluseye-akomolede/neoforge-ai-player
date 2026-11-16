Reviewed 807b6f1 (neoforge-ai-player, minecraft-wt-deepseek). Reviewer: minecraft-reviewer.

# 807b6f1

## (1) finding from 139def80: ordering check -- CLOSED
Ordering check now strips comments, takes the FIRST live guard, rc=2 on none, and
locates the extraction call in the SAME stripped text (like-for-like). All four
mutants redden, each on its own message. Evidence: clean `git archive` of 807b6f1,
serial runs under `timeout -k 5 90`, nice -n 19, clean re-control rc=0 after.

| mutant | rc | which layer fires |
|---|---|---|
| M-c only MODEL guard commented out | 2 | structure check: "no live guard ... or every guard is commented out" (0.099s) |
| M1 default restored `${MODEL:-qwen3-coder:30b}` | 1 | probe: "did not refuse for that reason ... has a default model again" |
| M2 guard block moved after `run.py` | 1 | ordering: "the MODEL refusal sits AFTER the extraction call" |
| M3 refusal message gutted ("missing input") | 1 | probe: judged on the message, not rc |
| M4 decoy guard early + real guard after extraction | 1 | probe (see limits) |

### The 139def80 finding is genuinely fixed
`refuse_blocks[0]` over comment-stripped text means a leftover block later in the
script can no longer be mistaken for the live guard. That was the wrong-target
diagnosis at 139def80; it no longer reproduces.

### M4: reddens through the probe, not the ordering check
With a byte-identical decoy at line 12 and the real guard at 61 (after the
extraction at 60), the ordering check alone reports "ok" -- first live guard wins,
which is correct-by-construction. The run fails because the *probe* executes the
matching script and the decoy produces the exact refusal bytes. So the two checks are
complementary layers and M4 is evidence they compose; it is NOT evidence that the
ordering check resists a decoy. Worth knowing before someone cites M4 for that.

## (2) job-evals.yaml digest -- CORRECT
2914fb85ff2220aefb63422767835eb71cb9c9710217105d8ed6d1d9c4880083 at :62 and :89,
identical to manifests base/minecraft/agent.yaml:142 at 2482fb5 (aibot-agent-test).
Prod e80c2e8b on :42 untouched; seed-profiles init 2026-11-05-c193f76 untouched.
Exactly one distinct sha256 in job-evals.yaml.

## Notes (not findings)
- `subprocess.run` at check_apply_matches_job.py:366 has no `timeout=`. On the input
  that hung for me it is unreachable (structure check returns 2 first), so the lead's
  hang hypothesis is falsified and this is NOT a demonstrated defect. Adding a timeout
  is cheap belt-and-braces; do not file it as a bug.
- The hang itself was MY harness: parallel background runs of the same probe. Serial
  rerun settles in 0.1s.

## Honest limit
I did not run the builder's five mutants as the builder wrote them; I built my own
four plus M-c in the shapes above. Each claim above is about the mutant I ran.

VERDICT: PASS
