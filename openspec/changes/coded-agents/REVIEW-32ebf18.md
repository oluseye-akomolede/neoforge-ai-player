# Review 32ebf18 — planner ownership split, relational tests, decline labels

Rev reviewed: `32ebf18` (`planner: ownership is not a precondition; labels and
relational tests`), on top of `ad2e077`. Read from `git archive 32ebf18`, not
from the builder's worktree.

Verdict: **PASS for the prompt and tests. The labels are unmeasured, not
measured** — they are correct decisions and correct data, but nothing ships
them into a run, so `decline_cases` will report `n=0` in the plan/replan after
leg the lead is about to rerun.

---

## Finding 1 (closed): the ownership bullet

`agent/l3_planner.py:369-377` no longer closes off clarify, and the
fabrication is named:

```
... if the task says the items are SOMEONE ELSE's ("put MY things in the
chest"), a player's items are not in the bot's inventory, and an empty bot
inventory means the bot does not have them. Fetching them from a place the
player can name completes the goal; filling the chest with unrelated blocks
produces a chest that is not what was asked for, which is the fabrication
this prompt forbids. If the owner or the source is genuinely unclear,
clarify — do not gather substitutes.
```

The bot's-own-items case stays a plan case ("put your things in the chest"),
so the split does not reintroduce the 11-15 regression it was written to fix.
`grep -n "gathers them" agent/l3_planner.py` → no match (rc 1).

The lead asked whether my wording landed as written. **It landed in
substance, not verbatim** — and only in the prompt. My proposed sentence was
`clarify whose things, and where they are`. The committed text says `If the
owner or the source is genuinely unclear, clarify` and **drops the "where"
half**, which was the second thing a bot cannot know. The clause is correct but
narrower than what I proposed. Worth a decision from the lead, not a blocker:
"put my things in the chest" with no chest named is still a clarify for the
reason the sentence no longer spells out.

## Finding 2 (closed): the preservation tests now test a relation

`_verdicts_for()` parses `* "<target>" → <verdict>:` off example lines only,
so prose mentioning a target yields `[]` rather than a false positive. I re-ran
the mutants from my `fdca63e` review against `32ebf18`:

| mutant | result |
|---|---|
| moon example → plan | 1 FAIL (`fly to the moon`) |
| bedrock example → plan | 1 FAIL (`dig to bedrock at the same time as X`) |
| "go get some stuff" → refuse | 1 FAIL (`test_clarify_examples_survive`) |
| delete the moon bullet | 1 FAIL |
| delete both refusal bullets | 2 FAIL |
| unmutated | 15 OK |

Every one reddens, including the two that stayed green under the old
string assertions. This closes the finding.

## Finding 3 (open, owned elsewhere): the labels never reach a run

The label file is `agent/output_evals/case_labels.json`; the loader is
`--decline-labels` at `run.py:408`, consumed at `run.py:208`.

* `git grep -n case_labels 32ebf18` → **no match**. Nothing in the tree names
  the file: not `evals/job-evals.yaml`, not `evals/make-evals-configmap.sh`,
  not `evals/check_apply_matches_job.py`, not a test.
* The loader's own docstring advertises `"refuse"|"clarify"`. Those are the
  cases where a decline is *right*. The builder added the third verdict,
  `"plan"`, which is the case the file exists for — the false decline — and it
  is the one the schema sentence does not describe.
* Consequence: the after-leg Job does not pass `--decline-labels`, so every
  kind reports `decline_cases: {n: 0, ...}`, and "not measured" reads as "no
  labelled cases" unless someone reads the key comment.

I verified the mechanism itself rather than reading it. Fixture case set from
the census (30 plan cases, all 5 labelled ids present), local stub endpoint
standing in for the model, outcomes forced by the cases:

| forced outcome | declined_correctly | declined_wrongly | missed |
|---|---|---|---|
| each case right (3 declines + 2 plans) | 3 | 0 | 2 |
| every case → clarify | 2 | 3 | 0 |
| no `--decline-labels` | n=0 (key present, zeros) | | |

*(`missed=2` above is correct for that forced run: two cases were labelled
`clarify` and the stub planned them. It reads oddly in the row because the
decline counts are the point.)*

The mechanism is sound and the counters separate the outcomes they claim to.
What is missing is the wiring, and the wiring is risky in one specific way: the
case ConfigMap must stay byte-identical across legs, so the labels have to ride
somewhere that is not the case set — a second ConfigMap mounted only on the
scoring container, or built into the image. That is the eval-harness row, not
this change.

## Finding 4: one label is a judgement I would re-check

`187451a0` (`plan`): "Scout, please store all your items in the nearby chest."
The label's `why` says an empty inventory means *gather first, then deposit*.
The corpus world state for that call is `inv_slots=0/36` and
`carried=[]` — nothing carried and nothing held, so "store all your items" is
"put nothing in the chest". Under `l3_planner.py:369` the task is *about
storing*, and the bot's own items are a bot-state precondition, so planning is
defensible. But the `why` should say which reading it takes, because the
alternative — this is the empty-inventory case where the answer is "you are
not carrying anything; store what?" — would label the same case `clarify`. The
label is probably right; it is not obviously right.

## Facts checked for the lead

* `case_labels.json` holds **5** labels, not the 4 the message names. The
  ambiguity resolves as: 2 correct declines (`b805c929` Tiller clarify,
  `45b2bf04` Scout clarify) + 1 more correct decline (`420efae5` moon
  refuse) = 3 that should decline, and 2 false declines (`187451a0`,
  `1d045e72`).
* The message says "2 correct (moon refuse, x2 'go get some stuff' clarify)" —
  that is **3**, and the "x2" refers to two *different* records
  (`b805c929` at `trajectory-2026-09-30.jsonl:11`, `45b2bf04` at
  `trajectory-2026-09-29.jsonl:125`), not one record counted twice.
* Every task text matches the corpus, read from the record rather than the
  model's reason. For the two clarify records `parsed.task` is `null` (the
  model answered clarify, so there is no plan object), and the task is
  recovered from the tail of `prompt_user`: `Task: Scout, go get some stuff`
  and `Task: Tiller, go get some stuff.` The other three carry `parsed.task`
  verbatim and I read each.
* All five records are `qwen3-coder:30b` — an older model than the fleet's
  `qwen3.8:27b`. That is fine for labels (a label is a judgement about the
  task) but it means these call ids exist only because that older model was
  recorded; a corpus rebuild that re-samples will drop them.
* The delta rode with the fix as the builder said: `openspec/.../spec.md`
  +31/−10, and the ownership split is in it.
* 15 prompt tests OK unmutated; the 117 evals tests and the 12 agent-suite
  failures are the builder's report, not re-run here — the failures are
  pre-existing on clean HEAD per the builder and are out of this rev's scope.

## Method note (my instrument, not theirs)

My first mutation pass on this rev reported five survivors. All five were my
harness: a `$OLD` expanded twice mangled the encoded dash/newline anchors so
the replace found nothing, and the runner then printed a green run of
*unmutated* code. The tell was a green result for a mutant whose edited line I
could grep. Every mutant now asserts the anchor is unique, prints the mutated
line, and aborts if the file is unchanged. Fifth session-level instrument bug,
same shape each time; the fix is the same each time — prove the mutation
happened before believing the tally.
