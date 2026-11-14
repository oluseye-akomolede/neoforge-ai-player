# Tasks

Order matters: the agent side is safe to ship alone (a non-thinking model
ignores `think`), but the gateway change must land before the test agent can
control thinking at all.

## 1. Agent: one setting, sent everywhere

- [ ] 1.1 Add `AIBOT_LLM_THINK` to `agent/config.py`, default `false`, parsed
      with the file's existing bool-env idiom.
- [ ] 1.2 Put the value on every `/api/chat` request body in `agent/brain.py`,
      `agent/criteria_eval.py`, `agent/planner.py` and `agent/l3_planner.py` as
      a top-level `think`.
- [ ] 1.3 Make the setting the only source: no call site may pass its own
      literal. Prefer one small helper over thirteen copies of the key.
- [ ] 1.4 Test: enumerate the agent's `/api/chat` request bodies (patch
      `requests.post`, assert on each body) and fail if any lacks a top-level
      boolean `think`. The test must fail against today's code.
- [ ] 1.5 Eval runner, separately: `agent/output_evals/run.py:54` is the 14th
      `/api/chat` site and takes its own `think` key from `evalconfig`, not
      `AIBOT_LLM_THINK` — the Job packs `output_evals` standalone and has no
      agent config or environment. Send it top-level on that request.
- [ ] 1.6 Test: the eval runner's request body carries `think` from its own key,
      and does not consult `AIBOT_LLM_THINK`.
- [ ] 1.7 `evalconfig.check_endpoint` gains a `think`-on probe: when the
      **resolved** `think` is `true` (from the file or the default), send one
      minimal `/api/chat` request carrying `think` and refuse the run (non-zero,
      no report) if it errors. `/api/tags` alone proves the model is present,
      not that the shape is accepted. The probe keys on the resolved value being
      true, not on a key being present in the file.
- [ ] 1.8 `evals/make-evals-configmap.sh` emits `think:` beside endpoint/model,
      from an env var, so the yardstick records it instead of leaving the runner
      to a default it never states.
- [ ] 1.9 `evalconfig`: add a typed `think: False` to `DEFAULTS` and
      **type-check it** like the other keys. Without the check a YAML
      `think: "false"` is a truthy string and the run thinks when the file says
      it does not — a silent wrong answer, which is the failure this change
      exists to prevent. Accept only a real bool (or the YAML booleans), and
      record whether the value came from the file or the default, the way
      `endpoint_from_env` records endpoint provenance.
- [ ] 1.10 Test: a config with no `think` line runs with `false` and the report
      says "default"; a config with `think: "false"` as a string is REFUSED; a
      config with `think: true` fires the endpoint probe.

## 2. Agent: do not read a truncated answer as an empty one

- [ ] 2.1 At the call sites that read `message.content`, distinguish
      `content == ""` with `done_reason == "length"` from an empty answer that
      is not truncated.
- [ ] 2.2 Test the distinction both ways, with the response body as the only
      input.

## 3. Gateway: forward think

The gateway repo has **no test harness**: `git ls-tree -r HEAD` lists 6 files
(`.gitignore`, `Dockerfile`, `app/__init__.py`, `app/main.py`,
`llm-planner-spec/l3-planning-layer-spec.md`, `requirements.txt`) and none of them
is a test. The marker is therefore not a drop-in against `format` — that analogy
holds for the code path, not for the test situation. Build the harness as part of
this task, or verify by another route and say which; do not write 3.3/3.4 as
though a suite already exists.

- [ ] 3.1 Add `think: bool | None = None` to `_OllamaShimChatRequest` with a
      comment in the style the `format` field already uses.
- [ ] 3.2 Forward it into the body sent to Ollama, next to `format`.
- [ ] 3.3 Stand up a minimal test harness in this repo (pytest, no network) —
      the first tests this repo has — and assert on the **outbound body**, not
      on the shim's parsed request: the bug being fixed was a field dropped
      between the two. `think: false` must appear.
- [ ] 3.4 Test: a request without `think` sends no `think` key.


## 4. Hand back to the lead

- [ ] 4.1 Report both commit shas. The lead runs the think-off vs think-on
      comparison on the same case set, picks the value from the numbers, then
      does every cluster step (test profiles, code default, verify, prod).
- [ ] 4.2 Do not change any model tag, profile or deployment setting in this
      change. That is the lead's, after it has the numbers.
