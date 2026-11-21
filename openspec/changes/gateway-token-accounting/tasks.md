# Tasks

## 1. Gateway passthrough (`llm-gateway`)

- [x] 1.1 `_process` keeps `done_reason`, `eval_count`, `message.thinking`
      from the upstream body instead of reading only `content`.
- [x] 1.2 `ChatResponse` carries the three fields as optional, so `/v1/chat`
      callers that ignore them are unaffected.
- [x] 1.3 The `/api/chat` shim reports them, replacing the hardcoded
      `"eval_count": 0`.
- [x] 1.4 `thinking` is omitted when upstream sent none, and present when it
      did, so a reader can tell "no thinking" from "thinking was empty".
- [x] 1.5 Unit tests: length→length, stop→stop, real count not zero, thinking
      present/absent, and every pre-existing field unchanged (additive check).
- [x] 1.6 Confirm no field removed or renamed against the pre-change envelope.

## 2. Guard reachability (`neoforge-ai-player`)

- [x] 2.1 Test that `answer_text` raises `TruncatedAnswer` for
      empty content + `done_reason: "length"` as delivered through the shim's
      envelope shape.
- [x] 2.2 Test that it returns `""` for empty content + `done_reason: "stop"`.
- [x] 2.3 Test that a body with no `done_reason` key does not report
      truncation.

## 3. Verification

- [x] 3.1 Mutant check: each new gateway test must redden when its field is
      hardcoded back to a constant.
- [ ] 3.2 After deploy, one real SCRIPT call reports a real `done_reason`,
      and the next trial's empty reply can be attributed.

## 4. Every structured call checks done_reason (2026-11-21, folds in c745c2af)

Raised by the lead on the 21:55Z trial: Axiom and Forge logged `subtask 1 exec
failed: model hit the token limit (done_reason=length, eval_count=768)` on the
L3 EXEC call, then retried at the same budget. Folds in row
`qitem-20261121193720-c745c2af07365244` (call_replan) at the lead's
instruction, so one rule covers both.

- [ ] 4.1 **Check `done_reason` before parsing, in every structured call.**
      Nine calls in `agent/l3_planner.py` request `num_predict`; only
      `call_plan` and `call_script` check `done_reason` before parsing.
      `classify_message` looked like it checked — a grep matched its
      neighbouring constant's comment, not its code. It does not.
      The five that parse a reply and do not check, with their literals:
      `call_exec` 768, `refine_skill` 768, `call_replan` 384,
      `partition_fleet` 400, `converse` 200; plus `classify_message`
      (`_CLASSIFY_NUM_PREDICT`, 128).
      KILLS: a test feeding a `done_reason=length` body with NON-EMPTY content
      must red for each call when the check is removed, and the error it
      raises must name the token limit rather than a JSON syntax error.

- [ ] 4.2 **`classify_message` must not swallow a truncation into a default.**
      It parses inside a bare `try` that logs and defaults to `"task"`, so a
      cut reply becomes a silently wrong classification rather than a failed
      call. A truncation MUST be reported, not defaulted.

- [ ] 4.3 **Each call's budget becomes a named constant sized by measurement.**
      Replace the literals above with per-call constants, each carrying the
      `eval_count` that justified it. 768 for `call_exec` was never measured;
      size it from a real exec call's `eval_count` at a budget it does not
      hit, not by copying `_PLAN_NUM_PREDICT`. Keep the existing rule that
      changing one constant never changes another call's `num_predict`.
      KILLS: a test asserting the budgets are mutually independent reds if any
      two calls share one constant.

- [ ] 4.4 **`call_replan` reports a length cut as a length cut** (was
      c745c2af). Today a 384-cut reply reaches `json.loads` and fails as
      `Unterminated string`, which reads as a malformed plan rather than an
      exhausted budget. KILLS: feeding a `done_reason=length` replan reply
      must raise the truncation error, not a `JSONDecodeError`.
