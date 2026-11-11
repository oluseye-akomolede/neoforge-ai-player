# v15 — Bot chat, stop, and ask-or-refuse

## Follow-up: in-game check of `df0bb8c` (2026-09-30)

The in-game check of the `df0bb8c` image on `minecraft-test` passed P2 (craft),
P5 (clarify), P6 (refuse) but **failed P7 and P4**:

- **P7 (stop)** — the bot said "Stopping. Standing by." yet the orchestrator then
  dispatched a `CHANNEL` directive and finalized the plan `complete`. The
  `execute_task`/`_step` checks added at `df0bb8c` guarded only the *attempt*
  boundary; a stop landing during the seconds-long L3 `call_exec` was set after
  that guard and the directives the call returned were still sent. Fixed by
  `b64f8c1` — checked after `call_exec` and before every dispatch, with a pending
  stop for the pre-publication window.
- **P4 (chat)** — "Hi Mystic! Who are you?" was dropped with no log line and no
  reply. Cause was **pre-existing**, not introduced by `df0bb8c`: `_maybe_plan`
  skipped any message whose lowercased text `startswith("hi ")` (or "hello",
  "hey", …). Fixed by `chat_filter.is_pure_pleasantry` — only a message that is
  *entirely* pleasantry is skipped — and both skip paths now log the drop.

Both fixes are agent-side, add no schema change, and are covered by new unit
tests in `agent/task_d_fixes_test.py`.

## Why

The qwen3-coder in-game run (minecraft-test, 2026-09-29 02:46–03:00Z) showed four
failures, all in how the L3 plan layer is entered and left rather than in the
model:

1. **P4 — every addressed chat became a task.** "Mystic, who are you?" went into
   `_run_orchestrator` like any order; the first message produced a 1-step
   `stand still 10s` plan and no reply. The agent had a conversation path
   (`l3_planner.converse`, with `BOT_PERSONAS`) but it was reachable only from
   the dashboard `/telemetry/talk` overlay — never from a player's chat.
2. **P7 — `stop` did not stop.** The `_stop_exact`/`_stop_phrases` shortcuts and
   `reset()` clear plan state on the agent's main thread, while the plan runs on
   the `orch:<name>` daemon thread. There was no abort channel between them, so a
   running plan kept dispatching subtasks after the bot had said it was standing
   by.
3. **P5 — a vague request was invented, not questioned.** "Tiller, go get some
   stuff" produced a loot-village + quartz-shelter plan the player never asked
   for. The planning prompt mentioned that L3 *may* decline, but nothing in the
   code carried a decline back to the player: `call_plan` validated any
   dict-shaped plan and `execute_task` executed it.
4. **P6 — a plan was reported `complete` with subtasks unfinished.** Scout's
   moon attempt ended `complete` after reaching bedrock. The
   `while plan.status == "executing"` loop exits "complete" when
   `current_subtask()` runs off the end, which also happens when subtasks were
   abandoned as failed. The plan status was the loop's exit condition, not a
   statement about the subtasks.

P4 and P7 are design gaps independent of the model; P5 and P6 are model
judgement behind a missing code path. This change closes the paths; the residual
P6 model limit is stated in "Known limits" below.

## What

- **Talk vs order split.** Before dispatching `_run_orchestrator`, one small L3
  call classifies the addressed message as `chat` or `task`. `chat` is answered
  via `l3_planner.converse` in the bot's persona and sent with `api.chat`; no
  plan is started. `task` behaves exactly as today.
- **Cost: a chat message costs two L3 calls** — the classifier plus
  `converse()` — and a task costs the classifier plus the plan it would have made
  anyway. One extra round-trip per addressed message. This is implementation
  detail, not spec'd behaviour; the spec states only the observable outcome.
- **Cancellation.** A per-bot `threading.Event` is created for each orchestrator
  run and checked by `execute_task` at the top of the subtask loop and by `_step`
  before each attempt, after the per-subtask planning call returns, and before
  each directive is dispatched. A stop that arrives before the run publishes its
  event is held as a pending stop and honored at publication. The stop shortcuts
  and `reset()` set it. The plan is finalized `cancelled`, not `complete`, and
  the bot says "Stopping."
- **Clarify / refuse.** The Phase 1 prompt may return
  `{"kind": "clarify"|"refuse", "reason": "..."}` instead of a plan.
  `call_plan` raises `PlanClarification`; `execute_task` turns it into a failed
  plan carrying `meta.declined` / `meta.reason` and speaks the reason in chat
  without dispatching anything.
- **Honest finalize.** Any subtask not `complete` at finalize forces the plan to
  `failed` and records `meta.unfinished_subtasks`. A genuinely complete plan is
  unaffected.
- **`cancelled` joins the plan lifecycle** as a terminal status alongside
  `complete` and `failed`.

## Non-goals

- No Java/mod change. The chat entry point (`inject_chat` →
  `BotPlayer.addChatMessage` → `chatInbox` → `drainChatInbox`) already carries a
  real player's line to the agent unchanged.
- No word- or entity-level blacklist for impossible tasks. With 18 dimensions
  registered on this modpack a word like "moon" can legitimately name a
  structure or item; a brittle heuristic here would reproduce the exact
  invent-something-plausible failure this change removes.
- No change to criteria evaluation, directive normalization, subtask retry
  counts, or the plan JSON schema beyond the new `cancelled` status value.
- No change to the dashboard plan API shape.

## Serialization impact

- `PlanStatus` gains one value: `cancelled` (`agent/plan_schema.py`). Readers
  must treat it as terminal and distinct from `complete`. Existing `_current.json`
  / archive files remain valid; no migration.
- `plan.meta` gains optional keys `declined` (`"clarify"|"refuse"`), `reason`
  (str), and `unfinished_subtasks` (str). All optional; absent on plans that did
  not decline or fail this way.
- No change to plan-store or archive file layout.

## Affected spec domains

- `l3-spec-driven-planning` — the plan layer's entry, exit, and status
  semantics.
- `bot-brain` — the bot's observable chat and directive behaviour. The change is
  agent-side, so `bot-brain` requirements are cross-references rather than state
  machine edits.

## Related

- Commit `df0bb8c` on `minecraft-wt-deepseek` implements this change.
- `~/minecraft-wt-deepseek/docs/qwen3-coder-ingame-results-2026-09-29.md` —
  the P4–P7 failure table this change answers.
- `~/minecraft-wt-deepseek/docs/task-d-chat-stop-clarify-results.md` — the
  in-game verification of `df0bb8c`.
- **v14** retired the fast-planner shim; **v13** added skill-output grounding.
  Both are L3-side; this change is the L3 plan layer's entry/exit contract.

## Known limits

P6's compound case ("fly to the moon **and** dig to bedrock") still plans: with
the strengthened prompt the model returns a 5-subtask route that substitutes the
End for the moon (`Teleport to the End` → … → `Dig down to bedrock`). Each
subtask's criteria are individually satisfiable, so neither the
`_criterion_impossible` evidence gate nor a deterministic rule can flag it — the
untruth is in the task→plan mapping, which is a semantic judgement. The decline
*mechanism* is proven by P5, which clarifies and speaks. The vague-task class is
fixed; the compound-impossible class is a residual model limit, not a missing
path, and is deliberately not papered over with a word blacklist.
