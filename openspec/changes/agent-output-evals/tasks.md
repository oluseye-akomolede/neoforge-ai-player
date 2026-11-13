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
      prompt + verbatim response + `criteria_eval` outcome for `plan`, `exec`,
      `replan` only. The other nine kinds are logged nowhere; `INVENTORY.md`
      says how each would be sourced, or that it is deferred.
- [x] 1.3 Write the proposal, this task list and the spec delta for
      `agent-output-evals`: eval-set format, scorer, size (30 per kind for the
      main planner), CLI + config for endpoint/model, report format.
- [ ] 1.4 Hand to the reviewer for a spec review; put the commit sha on the row
      (`qitem-20261113162928-37115062c5f6665a`).

## Step 2 — build (after reviewer PASS and the lead's OK; not started)

- [ ] 2.1 Eval-set extractor: read `agent_trajectories/trajectory-*.jsonl`,
      join `call` → `outcome` on `call_id`, redact secret-like values, write
      `evals/cases/<kind>.jsonl`. Exclude, and count separately, calls with no
      outcome.
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
