# CHECKPOINT at peak-park, 2026-11-16 00:53Z

State of review 807b6f1 (lead row, "ordering check fix + Job image pin").
Resume here after 04:00Z. Two of three requested items are DONE and logged below.
The third is INCOMPLETE and must not be reported as done.

## (2) Job image pin — VERIFIED, clean

`evals/job-evals.yaml:62` and `:89` both carry
`agent@sha256:2914fb85ff2220aefb63422767835eb71cb9c9710217105d8ed6d1d9c4880083`.

Checked against the reviewed commit rather than against a copy: `git show 2482fb5:base/minecraft/agent.yaml`
in ~/minecraft-wt-deepseek/manifests, line 142, inside the `aibot-agent-test` Deployment —
byte-identical digest. Prod (`aibot-agent`) is `e80c2e8b` on line 42, and the
`seed-profiles` initContainer on line 185 remains `agent:2026-11-05-c193f76`.
`sort -u` over every sha256 in job-evals.yaml yields exactly one digest, so no
second image is hiding at another line.

## (1) Ordering guard — PARTIALLY VERIFIED, one result outstanding

Code read at the rev: `evals/check_apply_matches_job.py:331-347`.
`live_script` strips comment lines; `refuse_blocks[0]` is the first live guard;
empty list returns 2; `src_extract` is located in the SAME stripped text, which
keeps the comparison like-for-like. This is the fix I asked for, and it is correct.

Mutants run (nice -n 19, no cluster):

    clean                                              -> rc 0
    M-a real early guard + leftover after extraction   -> rc 1, "sits AFTER the
                                                          extraction call"
    M-b commented-out guard above, real guard after    -> rc 1, same message
                                                          (previously caught only
                                                          by the probe; now by the
                                                          structure check indeed)

M-a is the exact shape that produced a WRONG diagnosis at 139def80 and it is now
right. M-b confirms the comment decoy is caught by the check that claims to catch it.

## OUTSTANDING — do not report PASS without this

M-c (comment out the only live guard, so there is no live guard at all) is expected
to return 2 with "no live `if [ -z "$MODEL" ]` guard". On this mutant the guard process
did NOT terminate within 300 s, twice. The structural code says it cannot reach its
own return, so the hang is either (i) the script being executed with MODEL unset
reaching a prompt or an interactive path, or (ii) my own harness. UNRESOLVED at the park.
Both hung runs printed NOTHING — not the guard's own PASS section, not a FAIL — which
means the guard never reached a verdict at all. That makes (ii) the likelier reading:
the clean control in the same batch printed a full PASS report first, and this mutant
differs from it only by my edit. My edit commented out the guard AND the lines inside
it, and the first thing the script does is the MODEL test that is now gone, so the
script falls through to the corpus/extraction path with a stand-in corpus. Whatever
the cause, the guard produced no output and the honest state is "not verified".
Do NOT read the missing output as a pass.

SETTLED at 04:0xZ. The hang was my parallel runs, not the guard. Rerun serial with
`timeout -k 5` from a clean `git archive` of 807b6f1: clean rc=0, M-c rc=2 in 0.099s
with the correct message ("no live guard ... or every guard is commented out"). My
first attempt at this rerun was ALSO wrong in a new way: I commented out the guard and
then ran `grep -c` against the SAME rewritten file, read the 0 as "the clean tree has
no guard", and very nearly reported that as a finding. Count against a kept copy of the
original (`orig.sh`), not the file you just edited.

The lead's hypothesis is falsified on this evidence: no subprocess timeout was needed,
because the structure check returns 2 BEFORE the behavioural probe runs. The probe is
unreachable whenever no live guard exists, so it cannot hang on that input. The absent
`timeout=` on subprocess.run at check_apply_matches_job.py:366 is still worth adding as
belt-and-braces (the probe is reachable on other inputs), but it is not a demonstrated
defect and must not be filed as one.

Also un-run: M-d (default restored, should now report the structure failure rather than
"has a default" — that is the builder's stated point of the reorder), M-e (message
gutted), M-f (reorder undone), M-g (comment filter dropped again).
So I have NOT confirmed the builder's "5 mutants each with their own message" claim.

## Ready for the peak-park

Nothing is pushed. 807b6f1 review is not written and not sent. The lead was told the
PASS is pending; if a seat wakes with this row, read this file first.
