# Review: script `api.say`/`api.send` delivered, not refused — `8e1b3a5`

**Rev:** `8e1b3a5` (on `62f44a0`, branch `minecraft-wt-deepseek`)
**Row:** `qitem-20261120222639-39a4111722a6189d`
**Verdict:** **PASS** on the delivered behaviour and the dry-tick guarantee as
written; **the spec's central bound sentence is false as deployed** (F1), and one
scenario asserts something the runner cannot do (F2). Neither blocks the repair;
both must be fixed before the spec is archived, because the spec would otherwise
claim a rate bound the product does not have.

Everything below was measured at a clean `git archive 8e1b3a5`, against
`agent-script-runner` at `7855a39` (the rev the runner runs), with no pod exec,
nothing applied to `ci`, and no request to `ollama-l3`.

---

## What the commit gets right

`say`/`send` are routed out of `translate_runner_actions` beside the `do`
records, so `bind_action` never sees them and the dispatch set is untouched.
Delivery reuses `api.chat` and `BotRunner.send_bot_message` — the planner's own
two paths, no new channel. Delivery runs before the `ran == 0` fallback, so a
say-only tick is not read as silence. `send_bot_message` returning `False`
(unknown bot) is counted as a non-delivery, which is the honest reading.

`Ran 98 tests ... OK`, rc=0 (`test_script_tick` + `test_agent_script_branch`).
Mutants: routing a `say` back through `bind_action` reds; not counting `False`
as non-delivery reds.

---

## F1 — the spec's rate-bound sentence is not true of the runner we deploy

The spec states:

> The runner's own rates bound this and remain the only bound: `api.say` 30/min
> and `api.send` 20/min per bot, enforced inside the runner (contract §8), so a
> script that calls them too often is already rate-limited before its records
> reach the agent.

The caps exist and are per-bot, and one tick cannot exceed eight records. But the
window they are counted in is **not** a minute of wall-clock. `acceptAction`
keeps a timestamp only if `at - t < 60_000` **from the last accepted call of that
kind** — it prunes from the newest now, not the oldest accepted one. Once a bot
has been quiet for 60 s, the array is empty and a full window is available again.
The window is therefore a refill-on-silence window, not a rolling minute.

Measured against `binding.js` at `7855a39`, one long-lived `botState` as the
sandbox holds it:

| Trace | Accepted | Rejected |
|---|---|---|
| 8 `say`/tick, ticks 1 s apart, 10 ticks | **30** | 50 |
| 8 `say`/tick, ticks 0.5 s apart, 20 ticks | **30** | 130 |
| 10 ticks, one tick per **full minute** | **800** | **0** |

The last row is the one that matters. A script that says eight lines once a
minute — exactly the cadence of the trial that motivated this change — is never
rate-limited at all: **480 lines an hour** against a cap the text calls "30/min".
The `MAX_HOST_CALLS = 8` per-tick cap is real but is a per-tick bound, not a
per-minute one.

This is the same species of defect the file already documents for `api.log`
("60 ticks x 8 lines = 480 lines produced 0 drops", the 6a755d6 defect). It was
fixed for logs and remains live for `say`/`send`.

**This does not make the commit wrong.** The spec also requires the agent to add
no second limiter, and I agree with that: the bound belongs in the runner beside
the one the logs already use. But the spec sentence asserting the bound is a
present-tense claim about the product that the product does not satisfy, and a
reviewer who signs it is signing something false. It should be either fixed in
the runner or restated as "the per-tick cap is 8; the per-minute window refills
when the bot is silent and is not a hard 30/min", before archive.

## F2 — "no message MUST reach another bot" is not enforced by the runner

`send` reaches `BotRunner.send_bot_message`, which appends directly to the
target's `chat_history` and `_new_messages` in-process and returns `True`. It
never posts `/inject_chat`, so the runner is not involved and has nothing to
refuse. `body["dry"]` is sent, but the runner at `7855a39` does not read it:
`grep -rn "dry" src/` over the whole runner returns **0** matches (positive
control: the same grep finds `createBotState` 6 times).

The dry guarantee therefore holds **only** because `ScriptTick.tick()` clears
`last_deliveries` when `self._dry`. That is genuine and I verified it three
ways: driving a real `ScriptTick(dry=True)` yields `last_deliveries == []`; the
real `_dry_tick` path issues 0 `api.chat` calls; and no code path reaches
`_deliver_script_deliveries` from a dry tick at this rev.

**But the guard is unheld by any test.** I changed the gate to `if False:` — a
live mutant: the same script under a dry tick then returns
`last_deliveries = [{'call': 'say', 'text': 'LEAK', 'seq': 1}]` — and the
**entire 98-test suite stayed green**, including
`test_a_dry_tick_never_reaches_the_delivery_path`. That test mocks
`ScriptTick` wholesale, so the record it hands back is never routed into
`last_deliveries`; it can only catch a refactor that merges the two call sites,
not one that stops clearing the list. The only other guard,
`test_dry_flag_reaches_the_runner_body`, asserts a flag the runner ignores.

This is not a live leak today — the review proves the code is correct — but the
spec makes "MUST NOT deliver anything from a dry tick" load-bearing, and nothing
would notice if the one line that enforces it were deleted. Recommend one test
that hands the real `ScriptTick` a dry tick with `say`/`send` records and
asserts `last_deliveries == []`, and a second that asserts nothing is delivered
when the dry flag is absent but the runner returns records.

## Notes, non-blocking

- **N-1 Loop risk: bounded, and correctly.** A delivered `say` is credited to
  `chat_history` by the mod, but `_maybe_plan` skips `sender == self.name`, so a
  bot cannot re-trigger on its own line. A `send` reaches the other bot with
  `from_bot = sender in _all_runners`, and the L3 trigger is
  `USE_L3_PLAN_LAYER and not from_bot`, so a bot-to-bot send never starts the
  other bot's planner; at most an L1 passive reaction or a taskboard claim. The
  real bound is F1: at one tick per second a script can put ~30 lines into chat
  per minute, and the per-minute window is not the hard bound the spec claims.
- **N-2 The delivery count is not a success count.**
  `_deliver_script_deliveries` returns the number of calls it did not skip.
  `api.chat`'s return value is discarded, so a `say` the mod rejected (HTTP
  error caught, or a `False`) is still counted as delivered and printed as such.
  The `send` path does check for `False`. Worth aligning if the count is ever
  used for anything but a log line.
- **N-3 Dry ticks still spend the record.** `dry` is in the body but the runner
  ignores it, so a dry tick runs the script for real and consumes the bot's
  actual `do`/`say` slots. Pre-existing at this rev, not introduced here, and
  the trial's concern rather than this review's.

## Not disputed

- The dispatch set is unchanged: `say`/`send` are removed before
  `bind_action`, and `_translate_one` refuses any non-`do` reaching it.
- `send`'s `msg` is stringified to the chat-path text; `say`'s `text` passes
  through; both keep the runner's `seq` beside, not inside, the record.
- One delivery failing does not stop the next (verified by the commit's own
  test, and the `try` is per-record).
- No file outside `agent/` and the spec delta changed.

Nothing built, pushed or deployed by this review.
