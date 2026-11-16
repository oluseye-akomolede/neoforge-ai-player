# REVIEW 93583d6 — H1 closed; the guard now does what its comment claims

Reviewed from `git archive 93583d6` into a fresh temp dir. Guard and runner both taken
from the rev. §H1 of `REVIEW-ceaf23a.md` is closed by this commit.

## The fix is the one I asked for, and it is right

`evals/check_apply_matches_job.py:174-176` now strips comment lines before matching:

    live = "\n".join(l for l in run_py.splitlines()
                     if not l.lstrip().startswith("#"))
    declared = set(re.findall(r'\badd_argument\(\s*"(--[A-Za-z0-9-]+)"', live))

and `:177-181` returns 2 when `declared` is empty, so an empty parse fails instead of
passing everything. Both are correct; the `\b` matters because it stops the regex
matching a longer identifier ending in `add_argument`.

## Mutants, run on this rev

    clean                                     -> rc 0
    M1 declaration commented at :434, call     -> rc 1
       otherwise intact
    M4 M1 plus a dead "ap.add_argument(...)"   -> rc 1
       literal in a comment elsewhere in the file
    M5 every add_argument( token neutered      -> rc 2

M1 is the exact probe that returned 0 on ceaf23a and 1 here: the anchor was the real
four-line declaration at `agent/output_evals/run.py:434`, commented with the rest of
the call left alone. M4 is the shape that defeats a naive "is the string anywhere in
the file" check; it still reddens, so the strip-then-match is genuinely a parse and not
a substring search. M5 shows the empty-parse guard is live rather than decorative.

## Note on my own route, recorded because it cost time

My first three attempts at M1/M4 this round did not run: two `sed` expressions were
unterminated and one Python anchor assumed the declaration ended on one line when it
spans four. All three printed `rc=0` because the mutation never applied and the clean
tree is 0. That is the same shape as the builder's stale-copy mistake on the same guard,
in the same hour: a green result from a mutation that did not happen. A mutant has to
assert its anchor before it runs, and the assertion output is the evidence that it did.

## Verdict

PASS for 93583d6 on H1. Combined with H2's staging guard (accepted in
`REVIEW-ceaf23a.md`), both findings from `REVIEW-16064a8.md` are now closed with
guards that redden on the shapes that defeated the earlier versions.
