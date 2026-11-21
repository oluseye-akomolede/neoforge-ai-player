# Review: 2e738dc - F-4 closed, option-2 scenario's unbind made reachable

Rev: 2e738dc (neoforge-ai-player, ship-ca27-harness)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21

## Verdict: PASS. F-4 closed. No new findings.

One file, +8/-5, spec text only. validate ai-written-scripts --strict at the rev:
"Change 'ai-written-scripts' is valid", rc=0, read unpiped.

## The fix

Old WHEN: "refuses every action for fewer than N consecutive ticks AND dispatches
on each intervening tick". I walked it at N=3/5/30 and the longest all-refused run
the WHEN admitted was 0 in every case - the AND asserted an N-run the WHEN
forbade, so a test written from the scenario could only assert the stays-bound
half and would have skipped the unbind, which is the whole point of option 2.

New trace, at 2e738dc:709-718:

  GIVEN  option 2 chosen; ticks have alternated refused and dispatched, so an
         all-refused run has started and been reset before
  WHEN   fewer than N all-refused ticks occur in a row, and then a tick dispatches
  THEN   stays bound, because that dispatch reset the count
  AND    a later run of N all-refused ticks with no dispatch between them ->
         unbound, reason in chat and in the log

Both halves are reachable now. The dispatch clause moved from the WHEN into the
GIVEN as prior history, so the reset is observed first and a contiguous N-run
follows in the same story. That is my second suggestion, and it is the better of
the two: one scenario with a connected narrative beats two scenarios whose
relationship a reader has to reconstruct.

## Checked

- validate --strict at 2e738dc: valid, rc=0, unpiped.
- Old WHEN wording "and dispatches on each intervening tick": 0 hits at the rev.
- One occurrence of the scenario name; no duplicate left behind by the rewrite.
- Reachability walked again on the new text: the AND's N-run is a *later* run,
  not constrained by the WHEN's "fewer than N", so nothing in the scenario
  forbids the N consecutive refusals it then asserts. Reachable for N>=1.
- "reason in chat and in the log" is consistent with this requirement's own body
  at :670 ("After N consecutive all-refused ticks, unbind the script and say why
  in chat and in the log"). This is NOT the phrase my F-2 on dd72746 flagged -
  that was option 1's stop-being-the-driver, where chat was deliberately removed
  from both the requirement and the task. Here chat is option 2's stated
  behaviour, so the scenario matches its own requirement. Worth stating because
  the surface phrase is identical and a later reader could "fix" it wrongly.
- The NOTE still scopes the scenario to option 2 and says shipped behaviour has
  no counter. Consistent with option 1's paragraph at :667-668.

## Nits, not findings

- The GIVEN says ticks "have so far alternated refused and dispatched", while the
  WHEN says "fewer than N all-refused ticks occur in a row, and then a tick
  dispatches". Strict alternation and "fewer than N in a row" are redundant with
  each other but not contradictory; the WHEN is the one that binds. No change
  required.
- "fewer than N" includes zero. A reader could ask whether a run of zero is a
  "run". Harmless in context - the THEN is about the reset, which a zero-length
  run trivially satisfies.

## Unaffected

The PASS on ddf7ebb (f8fa0b0) stands; F-1/F-2/F-3 stay closed. No code on this
row, so no suites run and none needed.
