# Review 9ad6930 — evals: rebuild in the Job, at n=25

**Verdict: PASS.** Supersedes my review of 3708de0 (N=14), which the lead overruled.
No code change required to merge. F2 carried over from 3708de0 is still open and
is the only finding that matters.

## Verified by running, not reading

Clean archive of 9ad6930, real corpus at /home/sigmastrain/minecraft-evals-corpus.

- **N=25 extract, all three kinds: 75 cases, 0 unscorable.** The builder's central
  claim holds.
- **Deferral is real.** plan 25/25 and replan 25/25 carry `recorded_prompt_system`
  with `prompt_system` empty; exec 25/25 carry `prompt_system`, none recorded.
  Extract leaves the prompt for the Job to fill, as designed.
- **The two-ConfigMap split reassembles.** `read_cases_dir` over two projected
  subdirs returns exec 25, plan 25, replan 25.
- **Sizes, both columns, reproduce exactly** as the script states them:
  exec 625757 raw / 845323 encoded; plan+replan 466844 encoded;
  all three together 1312167 encoded, 263591 over the cap.
- **The guard refuses the unsplit set** and prints both columns. F1 from 3708de0
  is fixed properly, not relabelled.
- **Rebuild runs from the shipped planner**: `import l3_planner` at run.py:341
  inside the Job path, with __file__ printed.

## The lead's three checks

1. Rebuild happens in the Job from the shipped l3_planner — **yes**, run.py:341.
   Not pre-rendered at extract time: extract parks the prompt and blanks the field.
2. N=25 fits the encoded cap — **yes**, as two ConfigMaps at 845323 / 466844.
3. Case selection identical across legs — **yes**, sorted pool + stratify()[:n],
   and the deferred case content is byte-identical since the prompt is rebuilt
   from the same recorded input.

## Answer to the lead's question: is the recorded prompt needed in the run?

Yes, but not as the scored artifact — as the rebuild's **input**. `_rebuild_plan`
recovers `dimensions` and `skills` from the recorded prompt; without it every case
would rebuild against the 3 vanilla-default dimensions instead of the 15 the model
saw. `differs()` also reports against it. So the field must keep shipping in the
case ConfigMap. The lead's plan is sound; the precision is that "recorded prompt
dropped from the case set" means dropped from *scoring*, not from the artifact.
Worth a comment so nobody later deletes it as unused.

## Findings

**F2 (carried, still open) — brace-tolerant parsing has no test.**
Every `criteria` in test_sysprompt.py is the literal "c". I replaced the
brace-counting loop in `_balanced_object` with "return at the first }" and all
14 tests stayed green, while on `{"a": "chest has {16} wheat", "b": 2}` the
mutant returns truncated JSON and the original returns the whole object. This is
the module's documented reason for existing. One fixture with a brace in criteria
fixes it. 9ad6930 added 67 lines of tests to this file and did not close it.

**F4 (new, minor) — comment accuracy.**
The script comment says the split is "affordable only because ... at N=25 all
three kinds in one map are 1312167 B encoded". Correct. But the earlier sentence
in 3708de0's shape said "N=19 keeps ~57 KB of headroom", which was raw bytes.
That specific line is gone; the current text is right. No action.

## T1 from 5ee0406 is closed

Deleting "If no prerequisite path can deliver the stated goal, decline rather
than substituting" now reddens two tests, including
test_no_prerequisite_path_means_decline. The builder fixed it by asserting the new
sentence rather than the pre-existing "you MUST decline" fragment.

## Mutation coverage of the prompt rules

- decline clause removed -> 2 FAIL
- speech-is-not-a-directive removed -> 1 FAIL
- MUST softened in replan -> 1 FAIL
All three new rules are genuinely pinned.

## Method notes

Two mutants told me SURVIVED when the cause was my harness: `unittest discover`
needs `-t .` in a clean archive and `agent/tests` has no __init__.py (run it
directly with PYTHONPATH), and a line-wrapped prompt string defeats raw
replacement. The tell each time was an implausible all-green. Also: unittest
printed a traceback and exited 0, so I checked PIPESTATUS rather than rc.

## Not verified

The two-ConfigMap Job itself has not been run by me or the builder — only the
code path. And the unscorable path has no live case exercising it.
