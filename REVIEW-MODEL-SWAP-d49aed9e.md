# Review: model swap to `qwen3.8:27b-q4_K_M` — PASS at `d49aed9e`

Rev: `d49aed9e` (`d49aed9`), neoforge-ai-player, branch `minecraft-wt-deepseek`.
Reviewed from `git archive d49aed9e` in a fresh scratch dir.

Owner decision via lead: all bots move to `qwen3.8:27b-q4_K_M` with think OFF,
test fleet first.

## Verdict

**PASS.** All three checks the builder asked for resolve in their favour, and I
verified each rather than accepting the reasoning.

## (i) The five values — correct

Read from the archive, per file, not from the diff:

| profile | model |
|---|---|
| axiom | `qwen3.8:27b-q4_K_M` |
| forge | `qwen3.8:27b-q4_K_M` |
| mystic | `qwen3.8:27b-q4_K_M` |
| scout | `qwen3.8:27b-q4_K_M` |
| tiller | `qwen3.8:27b-q4_K_M` |

`git diff --stat` confirms exactly 5 files, 5 insertions, 5 deletions. The string
matches the owner's model name character for character.

## (ii) Coherent with think-control — yes, and this is the load-bearing part

The builder's concern is correct and I verified the premise: a model swap to a
thinking model without `think=false` would be *slower*, not just different,
because the thinking step spends the small `num_predict` budgets these call
sites use.

Evidence the two ship together at this rev:

- `git merge-base --is-ancestor 4c33bc7 d49aed9e` → **yes**, think-control is an
  ancestor of the profile change. The swap cannot reach an image that lacks it.
- `config.py:130` — `LLM_THINK = os.getenv("AIBOT_LLM_THINK", "false").lower() in
  ("true","1","yes")`, default off.
- `config.py:133-139` — `think_field()` returns `{"think": LLM_THINK}`, top-level,
  sent explicitly.
- **12** `**think_field()` call sites in `agent/*.py` (brain ×2, criteria_eval ×1,
  planner ×2, l3_planner ×7), plus the runner's own `cfg.think` in
  `output_evals/run.py` fed from evalconfig.

So the new model reaches Ollama with `think: false` on every agent call site.

**The builder's live-pod claim is the one thing I cannot verify from this seat**
(`kubectl` is not installed here): that the running image `a9e75ad1` predates
think-control and sends no `think` field. It is consistent with what I know —
`a9e75ad1` was pinned before `4c33bc7` — and with the commit graph, since
`4c33bc7` is an ancestor of this change and not of that image. Stated as
consistent, not as confirmed by me.

## (iii) The two `agent.py` fallbacks — agreeing with the builder, with a distinction

`agent.py:183` and `:3780` still read `qwen3-coder:30b`. I checked the reach of
each rather than taking "they only apply to an omitted model" as one claim:

- **`:183`** — `profile.get("model", "qwen3-coder:30b")`, a per-profile default.
  I listed every file in `agent/profiles/`: five files, and all five carry
  `model`. So it is unreachable today. **Correct to leave.**
- **`:3780`** — `base_model = next(iter(_all_runners.values())).model if
  _all_runners else "qwen3-coder:30b"`, the hive-unit default. This is a
  different kind of site: hive drones and officers have **no profile file**, but
  they are constructed with `"model": base_model` explicitly (`agent.py:3797`),
  so they inherit the first runner's model — now `qwen3.8`. The literal fires
  only if `_all_runners` is empty, which cannot happen in a run that has loaded
  the five profiles.

Both are correctly left, but they are not the same hazard: `:183` is a
profile-local default and `:3780` is a fleet-wide one whose literal would send
hive units to a model nobody chose. Neither is reachable now. If a profile ever
omits `model`, `:183` silently reintroduces the coder model — which is why I
note it, while agreeing it is not this commit's job.

## Suites — run by me on the archive

| suite | result |
|---|---|
| `discover -s agent/output_evals/tests -t .` | **96 OK** |
| `test_profiles_dir` | **3 OK** |

Both match the builder's report.

## Gateway reasoning — verified

The builder's justification for editing profiles rather than gateway config:
`llm-gateway/app/main.py:96-100` declares `model: str | None = None` and honours
the client-sent model. I read it at the gateway's HEAD. So the profile model does
win over `L3_MODEL`, and the claim holds.

## Note, not a finding

- **The five model strings are not pinned by any test.** `test_profiles_dir.py`
  tests only which directory is used (3 tests: env honoured, unset falls back,
  empty string falls back); nothing loads the five real profiles and asserts a
  model. A typo in a future edit would be caught only by a bot failing to reach
  the model at runtime. Low cost to add, but not a blocker for this change and I
  am not asking for it tonight.
- `llm-gateway/app/main.py:95` has a comment naming `qwen3-coder:30b` as the
  example client model. It now describes history rather than the live fleet.
  Cosmetic; arguably better left, since the paragraph is about the historical
  dropped-field bug. Not this change's file.

## The live check the lead asked for — not run by me

A single `/api/chat` from the new image to `qwen3.8` with `think: false`
returning a non-empty answer is post-build, and I have no `kubectl` on this VM.
That check, and the image digest, belong to the build record; the builder owns
running it after the build and recording the result and rollback on the deploy
row.

## Build authorisation

This PASS authorises the build. It does not authorise rollout to the production
fleet: the owner's direction is **test first**, so the build → one live
`/api/chat` check → test-fleet rollout sequence stands, with the result and
rollback command recorded on the deploy row.
