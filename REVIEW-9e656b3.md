# PASS — 9e656b3 (planner-prompt-declines, spec delta only)

Reviewed from a bundle of `refs/heads/minecraft-wt-deepseek` into a scratch
clone. Parent `d49aed9e`. Three files, +280/-0, no code. Scope as described.

## Verdict

PASS. The change is correctly scoped, the delta is a faithful restatement, and
the two added decline rules are narrower than the risk they address. Two
findings go to the lead as spec decisions, not as blockers against this commit.

## Verified

- **Delta fidelity, mechanically.** Every line of both live requirements
  (`openspec/specs/l3-spec-driven-planning/spec.md` — *Phase 1 — Planning Call*
  at :127, *Replan on Repeated Failure* at :231) appears in the delta. 0 lines
  dropped, 0 scenarios dropped, 6 scenarios added (4 plan, 2 replan). The
  builder's "0 dropped, 9 added" counted differently (9 = 6 scenarios + 3 other
  additions); the direction and the absence of drops is right under either
  count.
- **The replan claim is right.** `_REPLAN_SYSTEM_PROMPT` at
  `agent/l3_planner.py:984` does end with `If truly impossible, return:
  {{"error": "<short reason>"}}`, inside the prompt whose spec'd contract is a
  single replacement subtask. The prompt invites an answer the spec forbids.
  That is a prompt defect against a live requirement, as the proposal says.
- **The capability-blindness claim is right.** `api.chat(` resolves at
  `agent.py:390,405,425,501,510,1271,1281,1368`, so speech is live behaviour
  that the directive catalogue does not represent. The proposal's citations all
  resolve.
- **The state-as-impossibility claim is right.** The existing refuse rule keys
  on world facts; an empty inventory is not one.

## Finding 1 (to the lead, not a blocker): line 1097 is a second escape hatch

`_REFINE_SKILL_PROMPT` at `agent/l3_planner.py:1097` also ends with
`{{"error": "<why it cannot be fixed>"}}`. This change removes the invitation
from `_REPLAN_SYSTEM_PROMPT` only. That is correct scope — the skill-refine path
is a different contract — but it means the change fixes the replan family and
leaves a structurally identical invitation one prompt over. If a later run shows
error-shaped skill-refine answers, the cause is the same and will not be found
by grepping for the replan text.

## Finding 2 (to the lead, not a blocker): the delta narrows decline reasons
## without saying what is now required of the alternative

The live requirement *Clarify or Refuse Instead of Inventing*
(`spec.md:500-507`) says declining is required rather than substituting "a
different, doable-sounding task; a plausible substitution is not an acceptable
plan". The delta says a transient precondition is "planned around". For "put my
things in the chest" with an empty inventory, planned-around means obeying an
instruction and contradicting one: either retrieve the items, or fail the
subtask and let the replan path handle it — a substituted plan the live
requirement forbids.

The delta's scenario (line 34) requires subtasks, which is right, but no
scenario says the plan must *obtain or carry* the items rather than substitute a
nearby task. The delta should either (a) state that planned-around means
retrieve-then-comply, distinguishing it from substitution, or (b) reference the
existing substitution rule so the two requirements are visibly reconciled.

Wait to put this on the builder next round, not this one — this commit does not
touch code, and the wording can be fixed with the prompt edit if the lead wants
it.

## Answer to Q1 (narrowed too far?)

No. The narrowing keys on a distinction that holds: *self-capability* and
*transient state* versus *world facts*. Every correct refusal the run recorded
(no moon) is a world fact and stays refused. The preserve-refusal and
preserve-clarify scenarios (delta :50, :57) pin both directions.

One residual: a model can read "planned around" as licence to invent a route to
anything, including the moon-via-new-dimension case the spec already forbids by
another route. That case stays covered by *Correct refusal of an impossible ask
is preserved*, so I am not treating it as a gap.

## Answer to Q2 (one change or two?)

One. The two rules live in the same prompt section and are the same instruction
expressed two ways: do not infer impossibility from something that is not a
world fact. Splitting them yields two deltas touching the same requirement and
two eval runs to say the same thing. The proposal's risk section is right that
the risk is fabricated plans, and that risk is only measurable by the joint
eval.

## Notes

- `openspec validate planner-prompt-declines --strict` re-run in the scratch
  clone at `9e656b3`: "Change 'planner-prompt-declines' is valid", rc=0. Run in
  the tree that holds the change, not in a worktree without it, and the rev was
  printed in the same command.
- The proposal says the 6th plan failure's text is not captured. That is stated
  honestly rather than characterised, and it is the right call.
