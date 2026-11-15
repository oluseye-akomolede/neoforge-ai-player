# Review — 3708de0 (eval harness rebuilds the system prompt from source)

**Verdict: PASS.** Three findings, none blocking; two are numeric errors in
comments/messages that should be corrected before they get quoted, one is a
real test-coverage gap.

Reviewed from a `git bundle` in a scratch clone. Parent `5ee0406`.
`git diff 5ee0406 3708de0` = 6 files, +656/-12.

## What I verified by running it, not by reading it

**The rebuild works end to end on the real corpus.** I ran the full corpus
(`--per-kind 100000 --rebuild-from-source --dry-run`):

    plan:   299 rebuilt, 0 unscorable
    replan: 271 rebuilt, 0 unscorable
    exec:   1543 not-run (correct - exec has no system prompt of this shape)

That confirms both of the builder's structural claims: replan *is* rebuildable
(contradicting the stale comment in extract.py:212), and nothing is lost by
readmitting it. 570 plan+replan cases, 0 unscorable.

**The two recovered inputs are faithful.** For 50 recorded plan prompts I
extracted the dimension list and skills catalog with the new helpers and
checked both come back as verbatim substrings of the recorded text: 50 ok,
0 bad. A recorded prompt carries 18 dimensions and a 2761-char skills catalog,
so the extraction is doing real work, not returning empties.

**The brace-counting parser is correct on its stated hazard.** A subtask whose
`criteria` contains `{16}` parses correctly (`chest has {16} wheat` survives
round-trip). Confirmed the mutant that stops at the first `}` returns `None`
on the same input — so this is a real capability, not a claim.

**Claim 2 (the live skills bug) reproduces.** With `EVALS_SKILLS_FILE` unset,
`skills_from_env()` returns `''`, which is falsy; `skills_from_env() or None`
converts it to `None` so the per-case fallback runs. The bug the builder
describes was real and the fix is the right shape.

**Claim 3 (1MiB base64 guard) is a real fix.** Measured directly:

    N=13  raw 673295   encoded  909541
    N=14  raw 726633   encoded  981593   (default; 67 KB headroom)
    N=15  raw 779380   encoded 1052854   (over by 4278)
    N=25  raw 1303790  encoded 1761264

The guard now measures encoded size and the script actually refuses N=15 and
passes N=14, verified by running `make-evals-configmap.sh` at both. The cap is
on encoded data; measuring raw undercounts by ~4/3 plus a newline per 76 chars.
That part of the fix is correct and worth having.

## Findings

### F1 — the sizes quoted in the script are the wrong column (fix before merge)

`evals/make-evals-configmap.sh:17-20` says:

> Measured over the 11-14 corpus, N=19 is 991052 B and N=20 is 1042935 B, so 20
> fits today ... 19 keeps ~57 KB of headroom under the 1MiB ConfigMap cap.

On the corpus present at `~/minecraft-evals-corpus`:

    N=19  raw  991052  encoded 1338792   (over by 290216)
    N=20  raw 1042935  encoded 1408882   (over by 360306)

**991052 and 1042935 are the RAW byte counts** - exactly the column this commit
exists to stop trusting. The encoded sizes are 290-360 KB *over* the cap, so
N=19 does not fit and never keeps 57 KB of headroom. The conclusion the comment
draws ("20 fits today") is false on the numbers it prints.

This is the same bug the commit fixes, reappearing in the commit's own
justification. Harmless to the running code (the guard checks the right thing
and `N=${N:-14}` is correct), but the comment will be quoted by the next person
choosing a value, and it points the wrong way.

Fix: reprint both columns from the encoded measurement. N=13/14/15 as measured
above are the useful anchors.

Same problem in the refusal message at the bottom of the guard:

    Lower N (currently 15) and re-run: N=14 fits, N=15 leaves under 10KB.

It refuses N=15 and in the same message says N=15 leaves under 10 KB. It is
4278 B *over*. Suggest: `N=14 fits (67KB headroom), N=15 is over.`

### F2 — brace-tolerant parsing is untested (real coverage gap)

`sysprompt._balanced_object` documents brace counting as the reason it is not a
regex: "a subtask's `criteria` is free text and may contain a brace, and a
greedy match would swallow the rest of the prompt".

No test exercises that. Every `criteria` in `test_sysprompt.py` is the literal
string `"c"` (lines 114, 123, 130) - no brace anywhere. Mutation confirmed:

    [balanced: stop at first }]  -> SURVIVED (all 12 tests green)

and on a real input with `"criteria": "chest has {16} wheat"` the mutant
returns `None`, i.e. silently turns a scorable case unscorable. The current
code is correct; nothing would keep it correct.

Suggested test: one replan fixture whose embedded subtask has a brace in
`criteria`, asserting the rebuild succeeds and the criteria survive intact.

### F3 — footnote, not a finding

`dimensions_from_prompt` returning `[]` instead of `None` on a miss also
survives mutation, but it is behaviourally equivalent: `_rebuild_plan` guards
with `if not dims:`, which is true for both. Worth knowing the two are
interchangeable here; no change needed.

## Not disputed

- **N=14 as the default.** The builder asked to be challenged. It is the right
  call on measured numbers: 981593 B leaves 67 KB, the largest value that does.
  The alternative (ship only the rebuilt prompt) loses the before/after diff
  that is the point of the leg. Keep N=14.
- The unscorable discipline: a case that cannot be rebuilt is refused, never
  filled with `{}`. The `default_factory` check on `recorded_plan`/`recorded_subtask`
  is the correct guard - the fields default to `{}` which is falsy, so a
  synthesised case cannot masquerade as a recorded one.
- Local imports in `sysprompt.py` so the replay leg still runs without
  `l3_planner`'s network stack. Right call, and documented.
- The copy of `agent/l3_planner.py` + `plan_schema.py` into the ConfigMap, with
  the stated bound (prompt from this commit, agent package from the image).
  Honest about what the leg claims.
- T1 from my 5ee0406 review is fixed: `test_planner_prompts.py:36,49` now
  asserts the new decline clause directly.
- Suite: 108 tests OK (`discover -s output_evals/tests`), agent suite 43 OK.

## Process note on my own harness

Two of my mutations first reported SURVIVED when the cause was me: an
`output_evals` import that only works from `agent/`, and a `for` loop that
reported RUN FAILED five times before I read the error (missing `--config`, no
`--corpus` flag - the other was `--trajectory-dir`). Both looked like results.
I re-derived every number from a command whose success I had confirmed.

