# Gateway token accounting passthrough

## Why

The a2 trial's SCRIPT call failed with `L3 SCRIPT call returned no block; raw
preview: ''` — HTTP 200 and empty content. The can't-tell-apart problem is that
this is also what a model with nothing to say returns, so the log cannot say
which happened.

The reason it cannot say is in the gateway. `llm-gateway/app/main.py:322`
reads exactly one field out of the upstream reply:

    content = data.get("message", {}).get("content", "")

Everything else the serving stack reported is dropped there, and the shim's
response envelope (`:398-411`) then fills the gap with `"eval_count": 0,  #
We don't break out token counts here` — a constant, not a measurement.

Measured 18:39Z on the deployed gateway, one chat call:

    top-level keys: ['_gateway', 'created_at', 'done', 'eval_count',
                     'message', 'model', 'total_duration']
    done_reason: absent entirely
    eval_count: 0

`agent/config.py:151` `answer_text` raises `TruncatedAnswer` only when content
is empty AND `done_reason == "length"`. Through this transport `done_reason` is
never present, so **that guard can never fire**. It has read as protection in
review since it was written and has never once run in this deployment.

This is the third instance of the same dropped-field bug class in this file,
and the file's own comments name the first two: `format` was dropped (silently
degrading JSON reliability) and `model` was dropped (every request served by
the 14b instead of the requested tag). Each was found the same way — a client
asked for something, and the gateway quietly answered a different question.

## What changes

- `_process` captures `done_reason`, `eval_count` and `message.thinking` from
  the upstream body instead of discarding them.
- `ChatResponse` carries them.
- The `/api/chat` shim reports them in place of the hardcoded `eval_count: 0`.

Additive only: no existing field is removed or renamed, and the `/v1/chat`
response model gains optional fields rather than changing required ones.

## Consumers checked before changing it

- `hive-service` — the only other k8s workload whose env points at the gateway
  (`LLM_GATEWAY_URL`, `app/config.py:30`). Reads neither `done_reason` nor
  `eval_count`; grep of `app/*.py` for both names returns nothing.
- `neoforge-ai-player` agent — the only reader of either field
  (`agent/config.py:161-166`), and it already handles the absent case.
- No other rig's deployments or services reference the gateway host; the only
  Service is `minecraft-test/llm-gateway`.

So the passthrough cannot break an existing consumer, which is why it is
additive rather than versioned.

## What this does not do

It does not explain why the SCRIPT reply was empty. It makes the next trial
able to say. If the empty reply turns out to be `done_reason: "length"`, the
budget is the problem. If it is `"stop"`, the model genuinely produced nothing
and the prompt or the request shape is the problem. Guessing between those now
would be the same mistake it fixes.
