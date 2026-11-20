# Tasks: script lookups (b) and script results (c)

Nothing in this change is code. Every task here produces or checks a document.
Code tasks appear only after the owner approves the spec and a later change
carries them.

## 1. Design approved

- [ ] 1.1 `design.md` passes `/egm-review` as a document: every `file:line`
      resolves, every recommendation has its alternative and why it lost, and
      §3's loop bound has a number that could be wrong.
- [ ] 1.2 Owner has read §3's cost sentence (up to 4 planner calls per hour per
      bot from results) and the §1 restriction (lookups answer only what the
      snapshot already carries), and has approved both.
- [ ] 1.3 Every radius in `design.md`, `tasks.md` and the spec delta is 5
      (blocks) / 16 (mobs) — the values `BotPlayer.java:619-620` caches — and no
      artefact still describes the requested radii as the served ones. Checked
      by grepping the change's own files for a claim that the snapshot covers
      radius 8 or radius 24; outside the §1 cost table, which compares cell
      counts on purpose, both must return nothing.
- [ ] 1.4 **Count lookup demand before 2.1.** Read the planner's actual scripts
      from the next trial and count how many would call a lookup at all, and of
      those how many need more than radius 5/16 or block state. This chooses
      **which lookups come first**; it does NOT gate step (b), which is the
      owner's explicit requirement.
- [ ] 1.5 Measure the cost of a wider radius before proposing one: time
      `getNearbyBlocks` at radius 5 (1331 cells) and radius 16 (35937 cells) on
      a test server, and record wall time per refresh. A number, not an
      estimate.

## 2. Lookups (b)

- [ ] 2.0 **Grow the snapshot before building `look`.** Add the registry id to
      each `nearby.blocks` entry and stop deduplicating by name
      (`BotPlayer.java:895-919`), so a lookup can match a kind and see a second
      instance. Pinned by a test asserting two chests both appear and each entry
      carries `minecraft:`-prefixed id.
- [ ] 2.1 A later change installs a `look` object beside `api`, built from the
      snapshot literal, with no reference to `api` and no host call.
- [ ] 2.2 Its results are deep copies. Pinned by a test that mutates a result
      and asserts the next lookup is unaffected; the mutant returns a live
      reference and must red it.
- [ ] 2.3 `hostCalls` is unchanged after many lookups. Pinned by a test; the
      mutant routes through `accept()` and must red it.
- [ ] 2.4 An out-of-range query says "not searched that far", not an empty
      list. Pinned by a test; the mutant returns `[]` and must red it.
- [ ] 2.5 The dry tick sees identical lookups. Pinned by a test running the
      same script dry and live against one snapshot.

## 3. Results (c)

- [ ] 3.1 A later change reads a script's return value and delivers it to the
      planner on exactly three triggers: `done`, error, `escalate`.
- [ ] 3.2 Size capped, truncated with a marker rather than dropped. Pinned by a
      test; the mutant drops and must red it.
- [ ] 3.3 The per-bot 4/hour cap and the 15-minute cooldown. Pinned by a test
      driving 10 ticks that asserts exactly one delivery; the mutant removes
      the cooldown and must red it.
- [ ] 3.4 The result renders into the next `call_plan` prompt as its own
      observation, with no extra LLM call. Pinned by a test on the rendered
      prompt and a test that no additional planner call is made.

## 4. Trials on test (run by the lead)

- [ ] 4.1 Lookup within the snapshot: a sheep goal shears only when a sheep is
      near. Counted from the log with grep.
- [ ] 4.2 Lookup beyond the snapshot: a diamonds-within-40 goal reports "not
      searched that far" and escalates, rather than silently doing nothing.
- [ ] 4.3 Result on completion: exactly one delivery, one planner call.
- [ ] 4.4 Result on error: delivered, not silently logged.
- [ ] 4.5 Loop bound holds: a script that claims `done` every tick yields at
      most 4 planner calls in an hour, with a non-zero drop count.

## 5. Out of scope, stated so it cannot drift back in

- [ ] 5.1 No live mid-tick lookup (Option B). A later request for one cites
      `design.md` §1 and the 8-host-call cap.
- [ ] 5.2 No change to the six-function API, the host-call cap, the rate
      windows, or the CPU budget.
- [ ] 5.3 No delivery of logs or actions to the planner.
