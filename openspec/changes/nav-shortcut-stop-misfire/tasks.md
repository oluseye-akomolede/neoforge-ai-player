# nav-shortcut-stop-misfire

## Tasks

Reported and written up on 2026-11-20 (lead handoff 19:02Z). Not fixed yet, by
direction. Reproduce from the trial log before starting; both halves are
observable there.

## 1. Reproduce

- [ ] 1.1 From the 18:57Z trial, confirm the message text, the
      `Direct stop (shortcut)` line, and that the goal was not created.
- [ ] 1.2 Confirm the two-goal damage: the same batch shows
      `honoring pending stop at orchestrator start` followed by
      `plan finalized: cancelled` on the *next* goal.
- [ ] 1.3 Write the failing test first, asserting both halves, so the fix has
      something to turn green.

## 2. Fix the matcher

- [ ] 2.1 A message is a stop command only when the stop phrase is what the
      message *says*, not something it contains. Decide the rule from the real
      chat the bots receive (short imperatives like "stop" and "halt" must keep
      working — they are legitimate and in `_stop_exact`).
- [ ] 2.2 Keep "stop following" working; it is an instruction about following,
      not a plain stop.
- [ ] 2.3 Cover the trial's sentence verbatim as a test case.

## 3. Bound the pending stop

- [ ] 3.1 A pending stop must not outlive the message that set it. Decide the
      bound (consume-once-and-expire, a timestamp, or clearing it when no
      orchestrator is live) and whether a *real* stop still needs it at all.
- [ ] 3.2 Test that a message which is not a stop cannot cancel a later goal.

## 4. Verify

- [ ] 4.1 Mutant: revert the matcher to the substring test and confirm the new
      test reddens.
- [ ] 4.2 Mutant: let the pending flag survive indefinitely and confirm the
      3.2 test reddens.
