# v15 tasks — Bot chat, stop, and ask-or-refuse

Agent-side only; no mod change. Implemented by commit `df0bb8c` on
`minecraft-wt-deepseek`.

## 1. Talk vs order

- [x] **`l3_planner.classify_message`** — one small L3 call
      (`format="json"`, `options={"temperature":0.0,"num_predict":24}`,
      `with ollama_lock`) returning `"chat"` or `"task"`. Any error, timeout, or
      unrecognised `kind` **fails to `"task"`** so an order is never silently
      dropped.
- [x] **`agent._is_chat_message`** — wraps the classifier; returns `False` on
      exception.
- [x] **`agent._reply_in_character`** — gets the persona from
      `l3_planner.BOT_PERSONAS`, current world state and directive, last 10
      conversation turns, calls `l3_planner.converse`, sends `api.chat(name, …)`,
      appends to `conversation_history`, pushes a `chat_reply` shared-state
      event. Failure replies "I didn't catch that — say again?".
- [x] **Both dispatch points** (~566 and ~759) — classify before
      `_run_orchestrator`; a `chat` message is replied to and consumed, and
      `execute_task` is never called.
- [x] **Greeting filter** (`agent/chat_filter.py:is_pure_pleasantry`) — a message
      that is *entirely* a pleasantry ("thanks", "ok", "hi Mystic!") is noise and
      is skipped; a message that merely *starts* with a greeting but carries real
      content ("Hi Mystic! Who are you?") is not. Replaces the old
      `startswith("hi ")` prefix test, which silently dropped the P4 message.
      Both skip paths now print a `[bot/chat] ignored (...)` line so a drop is
      visible in the log.

## 2. Stop cancels a running plan

- [x] **`agent._orch_cancel`** — a `threading.Event` created per run in
      `_run_orchestrator` and cleared in a `finally` when it is still the same
      object.
- [x] **`agent._orch_stop_pending`** — a stop/reset that lands before the orch
      thread has published its cancel Event (the window between thread spawn and
      `_orch_cancel = …`) is recorded and honored the moment the event is
      published, instead of being silently dropped.
- [x] **`agent._cancel_orchestrator(reason)`** — returns `False` when no run is
      live, else logs and sets the event.
- [x] **Stop shortcuts and `reset()`** — call `_cancel_orchestrator`; the stop
      shortcut replies "Stopping. Standing by.".
- [x] **`execute_task(cancel_event=)`** — checked at the top of the
      `while plan.status == "executing"` loop; sets `plan.status = "cancelled"`
      and breaks.
- [x] **`_step(..., cancel_event=)`** — checked before each attempt **and again
      after the `call_exec` returns** (a stop during the seconds-long L3 call is
      set after the pre-attempt check yet before any directive exists) **and
      before every dispatch in the directive loop** (a stop while an earlier
      directive runs must not let the next one go out). All three set `cancelled`
      and return `False`.
- [x] **Loop abort** — `failed` is only set when `_step` returns `False` and the
      plan is still `executing`, so a cancel is not overwritten by `failed`.
- [x] **`on_finalized`** — `cancelled` reports
      `Stopped — <done>/<total> steps done.`.

## 3. Clarify / refuse, and honest finalize

- [x] **`l3_planner.PlanClarification(kind, reason)`** — carries `kind`
      (`"clarify"`/`"refuse"`) and `reason`.
- [x] **`call_plan`** — a `{"kind": "clarify"|"refuse", "reason": …}` reply
      raises `PlanClarification` instead of validating and returning a plan.
- [x] **`_PLAN_SYSTEM_PROMPT`** — states that L3 MUST decline rather than
      substitute a doable-sounding task, with worked examples (fly to the moon →
      refuse; "go get some stuff" → clarify).
- [x] **`execute_task`** — `except PlanClarification` builds a failed plan with
      `meta.declined`/`meta.reason`, writes and archives it, and calls
      `on_finalized` with no subtask executed.
- [x] **`agent.on_finalized`** — a declined plan reports FAILED and speaks
      `meta.reason` in chat.
- [x] **Honest finalize** — before `plan_store.write`, a plan whose status is
      `complete` but which has any subtask not `complete` is marked `failed`
      with `meta.unfinished_subtasks`.
- [x] **`PlanStatus`** — `cancelled` added.

## 4. Evidence

- [x] **Unit tests** — `agent/task_d_fixes_test.py`, 27 checks, all pass:
      `(ulimit -v 4194304; python3 agent/task_d_fixes_test.py)`. Covers the
      chat/task split, classifier failure defaulting to `task`, cancel mid-subtask
      and between subtasks, unfinished subtask forcing failure (both the silent
      and the `_step`-returns-`False` shape), clean completion still completing,
      clarify and refuse both spoken with no subtask executed.
- [x] **In-game check** on minecraft-test through the real entry point
      (`api.inject_chat`), pod `aibot-agent-test-75b586cbd7-lqxrk`, image
      `chatstop2-dd88be0` (digest
      `sha256:e62ce57c0156ebe0749f866e8b4178e4ac29b3e44ba7c0e762953f52988be5fe`):
      P4 chat, P5 clarify, P7 stop all pass; P1 gather regression passes; P6
      partly (see proposal "Known limits"). Log lines recorded verbatim in
      `~/minecraft-wt-deepseek/docs/task-d-chat-stop-clarify-results.md`.
- [x] **In-game check of `df0bb8c`** (2026-09-30, `minecraft-test`, image
      `chatstop-df0bb8c`, pod `aibot-agent-test-589846d4b7-lzql7`): **P7 and P4
      FAILED.** P7 — "stop" printed "Stopping. Standing by." but the orchestrator
      then sent a CHANNEL directive and finalized `complete`. P4 — "Hi Mystic!
      Who are you...?" produced no log line and no reply. Both root-caused and
      fixed on `minecraft-wt-deepseek`: P7 = `_step` only checked the cancel
      event before an attempt (see §2); P4 = the `startswith("hi ")` greeting
      filter (see §1). Evidence:
      `~/minecraft-wt-deepseek/docs/v15-ingame-check-2026-09-30.md`.
- [x] **Unit tests — regression additions** — `task_d_fixes_test.py`:
      `test_stop_during_exec_call_dispatches_nothing` drives the **real** `_step`
      (the earlier cancel test patched `_step` out, so it never exercised the
      dispatch loop where P7 lived) with `call_exec` setting the cancel event
      mid-call; asserts nothing is dispatched and the plan finalizes `cancelled`.
      `test_greeting_prefix_does_not_drop_a_question` checks the pleasantry
      predicate, including that the exact P4 message is *not* treated as noise.
- [x] **Handoff** — review row `qitem-20260929045317-d08f6050` back to
      `minecraft-reviewer@minecraft` with the spec commit noted.

## Not done (deliberately)

- [ ] **P6 compound-impossible reliably declined.** Not a pending implementation
      task — the code path exists and is proven by P5. Recorded as a known limit
      in the proposal rather than closed by a heuristic.
