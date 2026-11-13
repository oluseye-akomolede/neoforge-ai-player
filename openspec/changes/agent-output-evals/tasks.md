# Tasks — agent output evals (step 1: spec only)

Step 1 is this change. **No code in this step.** Implementation tasks are listed
so the reviewer can see the shape and dependencies; they start only when the
lead OKs step 2.

## Step 1 — inventory and spec (this change)

- [x] 1.1 Inventory every place the agent asks a model for something, with
      file:line, which model it really uses, the output kind, its expected shape,
      and how correctness would be decided: `INVENTORY.md`, 12 live local calls
      plus 2 non-local ones excluded. Resolved the trap the lead flagged:
      `_deepseek_chat` (`skill_author.py:59`) and `l5.py:36` go to
      `DEEPSEEK_URL`, not `OLLAMA_URL` — online, out of scope. The local model
      tag lives in the profile (`agent.py:183`, all five profiles
      `qwen3-coder:30b`), not in `config.py`.
- [x] 1.2 Establish what is already recorded: `trajectory_log.py` holds
      prompt + verbatim response for `plan`, `exec`, `replan`, but an `outcome`
      record only for `exec` (`log_outcome` has one caller,
      `plan_orchestrator.py:616`, on `exec_call_id`; `call_plan`/`call_replan`
      do not return their `call_id`). `plan` and `replan` labels are derived via
      `plan_ref` + the plan archive. The other nine kinds are logged nowhere;
      `INVENTORY.md` says how each would be sourced, or that it is deferred.
- [x] 1.3 Write the proposal, this task list and the spec delta for
      `agent-output-evals`: eval-set format, scorer, size (30 per kind for the
      main planner), CLI + config for endpoint/model, report format.
- [x] 1.4 Reviewer round 1 (61728ce, 16:33Z) NOT PASS; three findings addressed:
      the `plan`/`replan` label join (it is `exec`-only — spec corrected to
      plan-level attribution via `plan_ref` -> `plan_close`, stated as weaker);
      the `semantic_memory._embed` miss (`nomic-embed-text`, local endpoint,
      named and scoped out with reasons); and `DIRECTIVE_KINDS` (37, mod) vs
      `_VALID_DIRECTIVE_KINDS` (35, agent — missing `AREA_LOOT`, `SKILL`; a live
      agent bug, filed separately). Its durability finding was WRONG -- the
      reviewer withdrew it at 16:35Z; `AIBOT_TRAJECTORY_DIR` IS set on the live
      pod and the files are on the Longhorn PVC. What is true is narrower: the
      Deployment was patched outside the repo, so a worktree grep cannot see it.
      The premise is deleted from proposal and tasks; step 2.0 now only re-counts.
- [x] 1.5 Lead direction (16:40Z note) applied, after the reviewer's round 1:
      the eval is a **replay** eval (recorded input re-sent to the configured
      model, new output scored automatically), with a **separate** historical
      outcome-attributed score — exec per call, plan/replan plan-level. Corpus
      measured live by the lead over every file on the PVC: exec 1545 calls /
      1530 outcomes; plan 299 calls; replan 271 calls; plan_close 359. Live
      model is `qwen3-coder:30b`. Durability is not a problem: `AIBOT_TRAJECTORY_DIR`
      is set in the pod and files are on the longhorn PVC; the spec reads the dir
      from config/env and does not hardcode it.
- [x] 1.6 Round 2 on de7e420: PASS with one correction (review 19d671c). The
      era-preference and the 30-minimum were jointly unsatisfiable for `replan`
      (current era holds 21). Precedence stated: current-era rate is the
      baseline for that kind, the shortfall reported, older-era cases only with
      the all-era rate shown separately, never blended.
- [ ] 1.7 Hand the correction to the reviewer; put the sha on the row.
- [ ] 1.8 File the agent's 35-vs-37 directive-kind gap (`_VALID_DIRECTIVE_KINDS`
      missing `AREA_LOOT`, `SKILL`) as a separate finding on the row — lead's
      direction — not fixed in this change.

## Step 2 — build (after reviewer PASS and the lead's OK; not started)

- [ ] 2.0 Re-count the corpus at build time (the lead's counts are the
      sizing evidence; the extractor prints its own), and report per kind and
      per model era. If a kind is short of 30, say so with the number.

- [ ] 2.1 Eval-set extractor: read the trajectory dir from
      `AIBOT_TRAJECTORY_DIR`,
      join `exec` `call` → `outcome` on `call_id`, and `plan`/`replan` `call` →
      `plan_close` on `plan_ref`; redact secret-like values, write
      `evals/cases/<kind>.jsonl`. Exclude, and count separately, calls with no
      label.
- [ ] 2.2 Scorer with unit tests, one module per kind family:
      schema/parse + kind/param surface for `plan`/`exec`/`replan`; label
      agreement for `classify`; coverage and real-bot-names for `partition`;
      "the rejecting validator accepts it" for `skill_refine`; goal reached
      within the step bound for `regenerate`.
- [ ] 2.3 Runner CLI + `evals/config.yaml` (`endpoint`, `model`, `timeout`,
      `concurrency: 1`); refuses to write a report when the case set is empty or
      the endpoint does not answer.
- [ ] 2.4 Report writer: endpoint/model from the config actually read, counts,
      per-kind rates, deferred kinds, failure examples.
- [ ] 2.5 Baseline run against the live local model as a bounded k8s Job the
      lead runs (one call at a time). Post the baseline numbers to the parent
      row `qitem-20261112065806-631db84f03dba1d7`.

## Inputs this change needs from the lead (no exec from the builder)

- [ ] L1 The read command for the agent's trajectory directory in the pod (or a
      copy out of it) so the baseline uses real recorded calls. Written into the
      run plan for the lead to execute.
- [ ] L2 One read-only log read for player chat lines, to source `converse` and
      `classify` inputs. If not granted, both kinds are deferred with a reason.
