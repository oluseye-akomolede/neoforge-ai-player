# Ollama think control

## Why

The owner asked (Slack 19:06Z, relayed by the lead) that the bots use the
model platform has installed on the V100s: `qwen3.8:27b-q4_K_M`. Platform keeps
only that tag loaded, pinned for 24h. All 15 bot profiles (10 test, 5 prod)
still ask for `qwen3-coder:30b`.

Moving the bots onto `qwen3.8` is not a tag swap. `qwen3.8` is a thinking model:
it emits thinking tokens by default, and **those tokens are counted against
`num_predict`**. The lead measured the failure directly, using the agent's own
request shape (`format: "json"`, `num_predict: 24`, no `think` field):

- `message.content` came back **empty**
- `done_reason: "length"`

That is a silent wrong answer, not an error. `agent/l3_planner.py` builds
requests with `num_predict` 24 and 200; on `qwen3.8` both shapes would spend the
whole budget thinking and return nothing. A parse failure there is
indistinguishable from a model that had nothing to say.

The fix is to let the caller say whether to think, and to default it off. Two
places must carry it:

1. **The agent** — one setting, sent as a top-level `think` field on every
   Ollama `/api/chat` call.
2. **The gateway shim** — the test agent reaches Ollama through
   `llm-gateway`, whose `_OllamaShimChatRequest` has no `think` field. Unknown
   fields are dropped, so today the agent *cannot* turn thinking off on the
   test path even if it sends the field.

The prod agent also talks to Ollama directly, so it needs only change 1; the
test agent needs both.

## What changes

- `agent`: a single `AIBOT_LLM_THINK` setting (default `false`), read once in
  `agent/config.py`, and carried as top-level `think` on every Ollama
  `/api/chat` request the agent makes.
- `llm-gateway`: `think` becomes an accepted, forwarded field of the Ollama
  shim request, following the same path `format` already takes.
- Out of scope for this change: switching profile model tags, running the
  think-on/think-off comparison, and any cluster step. The lead runs those.

## Why an explicit value and not "omit when off"

Omitting `think` leaves the decision to whatever default the serving stack
happens to have — which is exactly the assumption that just produced empty
content. Sending `think: false` explicitly is a property of the request, not of
the deployment, and it is testable without a thinking model to hand.

## Impact

- Affected specs: `agent-llm-transport` (new), and the gateway's Ollama-compat
  contract.
- Affected code: `agent/config.py`, every `agent` call site that posts to
  `/api/chat` (`brain.py`, `criteria_eval.py`, `planner.py`, `l3_planner.py`),
  `llm-gateway` `app/main.py`.
- No behaviour changes while `AIBOT_LLM_THINK` stays at its default `false` and
  the served model is not a thinking model: Ollama ignores `think` for models
  with no thinking capability.
