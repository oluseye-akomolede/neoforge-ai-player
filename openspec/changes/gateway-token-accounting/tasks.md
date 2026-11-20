# Tasks

## 1. Gateway passthrough (`llm-gateway`)

- [ ] 1.1 `_process` keeps `done_reason`, `eval_count`, `message.thinking`
      from the upstream body instead of reading only `content`.
- [ ] 1.2 `ChatResponse` carries the three fields as optional, so `/v1/chat`
      callers that ignore them are unaffected.
- [ ] 1.3 The `/api/chat` shim reports them, replacing the hardcoded
      `"eval_count": 0`.
- [ ] 1.4 `thinking` is omitted when upstream sent none, and present when it
      did, so a reader can tell "no thinking" from "thinking was empty".
- [ ] 1.5 Unit tests: length→length, stop→stop, real count not zero, thinking
      present/absent, and every pre-existing field unchanged (additive check).
- [ ] 1.6 Confirm no field removed or renamed against the pre-change envelope.

## 2. Guard reachability (`neoforge-ai-player`)

- [ ] 2.1 Test that `answer_text` raises `TruncatedAnswer` for
      empty content + `done_reason: "length"` as delivered through the shim's
      envelope shape.
- [ ] 2.2 Test that it returns `""` for empty content + `done_reason: "stop"`.
- [ ] 2.3 Test that a body with no `done_reason` key does not report
      truncation.

## 3. Verification

- [ ] 3.1 Mutant check: each new gateway test must redden when its field is
      hardcoded back to a constant.
- [ ] 3.2 After deploy, one real SCRIPT call reports a real `done_reason`,
      and the next trial's empty reply can be attributed.
