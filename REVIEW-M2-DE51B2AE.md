# Review — `de51b2ae` (scout.js idle-guard fix + 3 M2 plan corrections)

Reviewer: minecraft-reviewer@minecraft, 2026-11-12
Rev: `de51b2ae`. Parent `5d76c6f` (PASS, `a91cfdc`).
`openspec validate coded-agents --strict` → valid at `de51b2ae`.

**Verdict: PASS, with one HOLD on documentation only (not on the code).**

---

## 1. The bug and the fix — verified by running it

`get_directive` is a raw pass-through (`api.py:43-45`), so `snapshot.task` is
the mod's response object. An idle bot reports an object, never null, so
`if (snapshot.task) return []` held on every tick. Confirmed by reading the
producer chain: `snapshot.py:76` `"task": directive` → `:144`
`build_envelope(..., task=state.get("task"))` → envelope `task`.

Guard at `scout.js:63-65`:

    var task = snapshot.task;
    if (task && !(task.progress && task.progress.phase === "idle")) return [];

### Polarity, measured through the real script (the builder's question 1)

Driven with the envelope shape `SnapshotCache.get` actually produces:

| `task` shape | result |
|---|---|
| idle (real captured object) | **acts** — `[{"kind":"STORE_ALL"}]` |
| busy (real captured object) | holds |
| object present, **no** `progress` block | holds |
| `progress` present, **no** `phase` | holds |
| `task: null` | acts |

The unknown-shape polarity is right: every unreadable shape holds. `task: null`
acting is also right — no directive at all means nothing is in flight, and
holding there would leave a fresh bot permanently idle.

This matters more than "safe direction" usually does, because **the script guard
is the only thing preventing a second directive**. `_run_script_tick`
(`agent.py:2652`) dispatches whatever the script proposes with no in-flight
check; the ACTIVE guard at `:3675` belongs to the separate standing-orders path.
An unsafe polarity here would stack a job under a live one.

### The suite catches the regression

Clean `git archive de51b2ae`, run from `agent/`:
- unmutated: **Ran 7 tests, OK**
- restoring `if (task) { return []; }`: **FAILED (failures=2)**, including
  `test_real_idle_directive_does_not_silence_the_script`.

The mutant dies, so the test covers the guard it is named for.

---

## 2. Fixtures vs producer (the builder's question 2)

`IDLE_DIRECTIVE` and `BUSY_DIRECTIVE` (`test_scout_script.py:74-85`) match the
two live responses quoted on the row field for field, and `_envelope` now
defaults `task` to `IDLE_DIRECTIVE` rather than `None` — the fixture-vs-producer
fix, correctly placed. The naive `{"type":"MINE"}` busy fixture is gone; that
shape was never returned by the mod.

**But the corroboration I looked for does not exist, and it is worth knowing.**
The only other reader of `progress.phase` in the repo is `agent.py:2278`, and it
reads it from `brain_state = api.get_brain(...)` (`:2200`) — a **different
endpoint** from `get_directive`. So that line is not independent evidence that
`/directive` carries `progress.phase`; it evidences `/brain`.

The contract (`contract-v1.md:198-210`) says `task` is "game-specific, opaque"
and its one example is `"task": { "goal": "…", "progress": 0.5 }` — `progress`
as a **number**. Under that shape `task.progress.phase` is `undefined`, the
guard reads it as busy, and the script holds forever. This is not a defect in
the fix: the builder measured the live response twice and the fixture is the
measurement. It is a **contract gap that the fix now depends on**.

---

## 3. HOLD (documentation, one paragraph)

`contract-v1.md` must record what the Minecraft binding actually puts on
`task`, or point at where it is recorded. As written, a future binding — or a mod
change that makes `progress` a number — silently converts the guard into a
permanent hold, and the failure looks like "the bot is busy", not "the contract
moved". The plan's §3 correction should also note that the guard depends on this
shape.

Not a blocker for this run: `/directive` is measured to carry it today, and
`de51b2ae` is correct against the live response. It is a blocker for calling the
snapshot schema specified.

---

## 4. The three plan corrections — all sound

1. **Evidence row 1** now reads the tick RESPONSE, with the reason recorded:
   `server.js` logs only startup/shutdown/errors, so a successful tick writes no
   line. The old row would read the same for zero ticks or a thousand.
2. **The run-1 control `78 → 78 (no change)`** is marked vacuous and replaced by
   the agent-side `[Scout/script]` tick count. A control that cannot move is
   worse than an absent one; this is the strongest correction in the commit.
3. **"Script mode is not a live toggle"** — `_script_loaded` caches on first
   tick (`agent.py:2797`); the 6-minute stale-ConfigMap observation matches the
   code.

Row 5's pass condition moved from the runner log to the tick response for the
same reason as (1). Correct.

---

## 5. Nit, agreed with the builder

`COPY . .` ships `test_directive_param_filter.py` into `/opt/aibot-agent/`.
Inert (nothing imports it), already noted in §8.3.2. Excluding `test_*.py`
alongside the existing `rm -rf ./scripts` would be tidier.

---

## 6. What this review did not verify

- The two captured directive shapes are the builder's live measurement. I
  reproduced their *behaviour* through `scout.js` and confirmed they match the
  fixture and the producer chain, but I cannot reach TEST to re-capture them.
- The 101-test full-suite figure and the dashboard/uvicorn ImportError are the
  builder's; my instrumented run covers `test_scout_script` (7 tests) and the
  eight-module set used in prior reviews.

## 7. Reviewer process note

Three instrument failures before a clean measurement here, all mine: I passed
the task object as `snapshot` instead of `{"task": ...}`, and read the resulting
`undefined` as "the guard is inverted". The script hashes matched the commit
throughout — the file was never wrong. Running the mutant and the polarity table
on the real envelope was the only way to get an answer; reading the guard would
have agreed with either story.
