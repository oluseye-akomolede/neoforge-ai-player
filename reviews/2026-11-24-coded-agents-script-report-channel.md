# Review — coded-agents 5.6/5.7/6.4: script report channel, both ends

- **Row:** `qitem-20261124041104-918d376a7d3a785c`
- **Commit:** `435e14b` on `ship-ca27-harness` (not in `minecraft-wt-qwen`'s history; read by sha)
- **Reviewer:** minecraft-reviewer@minecraft
- **Verdict:** **PASS with findings.** No blocker: F-1 and F-2 are design/document defects for
  the lead's design review and 5.4; F-3 is prose. Product code is sound and I found no defect
  in it that changes an outcome.

Everything below was read or run from a clean `git archive 435e14b` at `/tmp/r435`, not from
the builder's worktree.

---

## What I verified, and how

**Python.** `test_script_report.py` (19) + `test_script_tick.py` (141) → **160 OK**, rc=0, run
with `python3 -m unittest` from `agent/`. The build commit claims 173 overall; the difference is
other modules, not a discrepancy in this file.

**The design's new rule is pinned by a test.** Replacing
`float(code_hours) < prev["code_hours"]` with `True` (i.e. "always present", the old behaviour)
reddens `test_absent_on_a_rise`. Restored, green.

**Sender matches the design line-for-line.** `script_report.py:123`:
`if prev is not None and float(code_hours) < prev["code_hours"]:` — present only on a fall.

**Receiver validates rather than trusting.** `ScriptReportStore.record()` refuses an empty
`script_state` or `observed_at`, refuses an unparseable stamp, refuses non-finite/negative/
over-cap hours and ticks, refuses a non-finite previous. It does not guess. `staleAt()` may
trust the parsed stamp precisely because an unparseable one never got stored.

**Both surfaces carry it.** `handleBotAction`'s `script_report` case stores; the `status` route
a player fetches merges it. The figure reaches the player, not just `/bots`.

**Payload.** 225 bytes on the test's named payload with every field at cap, printed by the test
itself on its own serialiser — reproducible, unlike the figures withdrawn the previous day.

**`previous_code_hours` is `None`, not `null`, when absent.** `build_body` omits the key.

---

## F-1 — The design contradicts itself on what "unlabelled" means (document defect)

Two passages in `design.md` at `435e14b`:

- `:143-147` (predates this work, present since `1f524a5`): *"What it must not do is show a
  figure falling from 1.4 h to 0.0 h **unlabelled**."*
- `:204-214` (added by my own F-3 fix at `2586ecc`): a restart's fall **is** unlabelled, cannot
  be labelled from this payload, and whether it must be is **5.4's**.

`2586ecc` added the second bullet without amending the first — I checked that directly: `2586ecc`
adds the "What a fall is observable for" bullet and does not touch the `unlabelled` sentence,
which is present verbatim at both commits.

Under the *old* rule the two sentences were compatible: `previous_code_hours` was present on
every report after the first, so the restart report carried its `1.4 h`. Under the **new** rule
(`absent unless LOWER`) a restart's first report has no previous — so it *is* the unlabelled
case, and the `:147` sentence forbids exactly what `:204-214` documents as unavoidable.

This is a genuine hole and partly mine: I approved the F-3 bullet on its own accuracy without
re-reading the rest of the document for agreement. **The fix is one clause at `:147`** —
"unlabelled" should read "unlabelled except where the previous report is unavailable (a
restart), which is 5.4's to label or not" — or the bullet at `:147` should point at `:204-214`.

Not blocking: it is an unreleased spec delta and no code reads the prose. But the lead's design
review will read both sentences.

## F-2 — `tasks.md` 5.7's deviation is filed under 6.3 (document defect)

`tasks.md` records three deviations. Two are correctly placed. The third — the one that matters
most, since it is a departure from the task text — is not.

`5.7` says the report is stored *"per bot on `BotPlayer`"*. The build does not do that; it uses a
static `ScriptReportStore`, with a sound reason (BotPlayer is per connection; the report must
survive a reconnect). But that deviation record is filed under **6.3**, whose text is *"Prove no
endpoint accepts script text from a player"* — unrelated to storage. And 5.7 reads as if built as
written.

The builder disclosed this in prose in the row ("the store is a static ScriptReportStore rather
than a field on BotPlayer") and I credit that — but the record belongs under the tick it
deviates from, or a reader ticking 5.7 off cannot see it.

## F-3 — Three setup paths report a state the receiver refuses (minor, code)

`script_tick.py` assigns `last_state` before every *outcome* return, and the comment says why:
so a refused or timed-out tick never reports a stale state. That is careful and correct — I
checked a refused tick reports `fallback_*`, not the previous state.

But three **setup** early returns (`no script`, `no_token`, `no_runner`) return above that
assignment with `last_state` still `None` on a bot's first tick. The reporter is called
unconditionally after `st.tick()`, builds `state=None`, and `report()` raises before posting;
the seam's blanket `except Exception: pass` swallows it. Effect: nothing is recorded and the
dropped-report counter does not move — silent, but self-healing (the next valid tick posts).

Two smaller notes in the same seam:
- `hours = meter.usage_hours() if meter is not None else None` is dead: `_record_code_time_tick()`
  runs immediately before and guarantees the meter exists. Harmless, but it reads as a live
  branch.
- Routing `state=None` into `build_body`'s `state.upper()` is the mechanism of the throw above;
  guarding it would surface the three paths rather than silently dropping their reports.

No user-visible consequence today. It matters if anything ever counts reports.

## Recorded, not endorsed

- **The design change arrived inside the code commit.** `git show 435e14b -- design.md` is one
  line, authored by the shared `sigmastrain` identity, with no separate design diff to review.
  The builder flagged that they did not author it and cannot attribute it, and that it matches
  the sender they wrote. Both true as far as the repository can show. Consequence: my previous
  PASS on the design (`ec954a4`) does not cover this line, and no commit separates the design
  change from the code that implements it.
- **The `previous_code_hours` name now under-describes the field.** It is present only on a
  fall, so a reader trusting the name expects a delta on every report. The design row says so
  explicitly; the name does not. Cosmetic, but it is the kind of mismatch that generates a
  "bug report" against working code later.
- **F-2 from the code-time row is still open** (`is_exhausted()` survives a `return False`
  mutant). Unchanged by this commit; 5.4's to close.

---

## Reproduction

```
git -C ~/minecraft-wt-qwen/neoforge-ai-player archive 435e14b | tar -x -C /tmp/r435
cd /tmp/r435/agent && nice -n 19 python3 -m unittest test_script_report test_script_tick
# 160 OK
# design-rule mutant: script_report.py:123 'float(code_hours) < prev["code_hours"]' -> True
#   reddens test_absent_on_a_rise ; restore -> green
cd /tmp/r435 && gradle --offline test --rerun-tasks   # needs a seeded .gradle/caches/minecraft
```

**Java, measured.** `--offline test --rerun-tasks` at `/tmp/r435` with
`.gradle/caches/minecraft` seeded from the warm worktree: **BUILD SUCCESSFUL in 53s**,
**97 tests across 11 classes, 0 failures, 0 errors**, read from the JUnit XML rather than the
console. `ScriptReportStoreTest` is 14 of them (87 elsewhere — the 83 pre-existing plus a few
added since the harness row). The first attempt failed with zero tests and no `> Task :test`
line: `--offline` cannot build a cold archive, the same cold-cache hazard as before. That
failure is an instrument fault, not a red suite, and seeding the cache is what resolved it.
