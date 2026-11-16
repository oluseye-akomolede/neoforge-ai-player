# REVIEW 139def80 — PASS, with one finding and one untested shape

Reviewed from `git archive 139def80` into a fresh temp dir, guard and script both from
the rev. Tests run `nice -n 19`, no cluster access.

## What is verified

The script refuses when `MODEL` is unset, and the refusal is the first substantive
statement in it — `evals/make-evals-configmap.sh:46-53`, above the corpus check, the
extraction, and every other input test. `MODEL=${MODEL:-}` keeps `set -u` from killing
it before it can explain itself. No default is left anywhere that executes.

The guard at `evals/check_apply_matches_job.py:319-354` avoids both traps the builder
named:

- **Not exit-code-only.** It runs the script with `MODEL` removed from a copied
  environment, on an empty stand-in corpus, and requires `"MODEL is unset"` in stderr.
  M1 (default restored) and M2 (block moved after extraction) both exit 3 for unrelated
  reasons — extraction failing — and are both rejected on the message. The builder's
  point stands: rc would have passed both.
- **Not first-occurrence.** It anchors on `if [ -z "${?MODEL"` and takes the **last**
  match rather than `find()` of the message text.

## Mutants

    clean                                        -> rc 0
    M1 default restored to qwen3-coder:30b       -> rc 1, "did not refuse for that reason"
    M2 block moved after extraction (no decoy)   -> rc 1 (via the runtime probe)
    M2b same, plus a real early guard + the      -> rc 1, "refusal sits AFTER the
        original block still after extraction       extraction call"
    M3 refusal message gutted                    -> rc 1, "did not refuse for that reason"
    M4 message only in an early comment, block   -> rc 1 (runtime probe)
        after extraction

All three mutants the lead named go red. M2 does not reach the ordering check on its own
— see the finding — but it is rejected, by the runtime probe.

## Finding: the ordering check can flag the wrong guard

`refuse_blocks` uses `re.finditer` and takes `refuse_blocks[-1]`, with no filter for
comment lines. M2b: a deliberate, working early guard at `:50`, the original block
moved to `:73`, and the check reports "the MODEL refusal sits AFTER the extraction call"
— pointing at `:73`, which is not the guard that runs. The verdict is right and the
diagnosis is wrong, in the direction that matters less: it accuses the script of a defect
it does not currently have.

The shape the builder's comment names — a decoy that would pass a `find()` — gives the
opposite result. A commented-out `# if [ -z "$MODEL" ]; then exit 1; fi` above the
extraction and the real guard below it returns "did not refuse for that reason", so it is
caught, but *by the runtime probe*, not by the ordering check the comment credits.

Fix: strip comment lines before matching, as the H1 arg guard in the same file now does —

    live = "\n".join(l for l in script.splitlines()
                     if not l.lstrip().startswith("#"))
    refuse_blocks = [m.start() for m in re.finditer(r'if \[ -z "\$\{?MODEL', live)]

and take `refuse_blocks[0]`, so the position tested is the first guard that actually
executes. Return 2 if the list is empty, as elsewhere in this file.

## Untested shape

No mutant leaves the script treating an *empty* `MODEL` and an *unset* one differently.
`MODEL=""` is refused by the same `-z` test, so the current script behaves correctly;
I am noting that nothing pins it, not that it is broken.

## Verdict

PASS for 139def80. The finding is a quality defect in the diagnostic, not a hole in the
refusal, and it does not block the lead's run.
