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
      literal. Prefer one small helper over fourteen copies of the key.
- [ ] 1.4 Test: enumerate the agent's `/api/chat` request bodies (patch
      `requests.post`, assert on each body) and fail if any lacks a top-level
      boolean `think`. The test must fail against today's code.

## 2. Agent: do not read a truncated answer as an empty one

- [ ] 2.1 At the call sites that read `message.content`, distinguish
      `content == ""` with `done_reason == "length"` from an empty answer that
      is not truncated.
- [ ] 2.2 Test the distinction both ways, with the response body as the only
      input.

## 3. Gateway: forward think

- [ ] 3.1 Add `think: bool | None = None` to `_OllamaShimChatRequest` with a
      comment in the style the `format` field already uses.
- [ ] 3.2 Forward it into the body sent to Ollama, next to `format`.
- [ ] 3.3 Unit test: the forwarded Ollama body carries `think: false`. Assert
      on the outbound body, not on the shim's parsed request — the bug being
      fixed was a field dropped between the two.
- [ ] 3.4 Unit test: a request without `think` sends no `think` key.

## 4. Hand back to the lead

- [ ] 4.1 Report both commit shas. The lead runs the think-off vs think-on
      comparison on the same case set, picks the value from the numbers, then
      does every cluster step (test profiles, code default, verify, prod).
- [ ] 4.2 Do not change any model tag, profile or deployment setting in this
      change. That is the lead's, after it has the numbers.
