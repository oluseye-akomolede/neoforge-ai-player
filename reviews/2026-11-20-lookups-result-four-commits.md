# Review: lookups + api.result — `5a25358`, `2bcc78f`, `9f80538`, `ddaf29f`

**Repos:** `neoforge-ai-player` @ `ddaf29f`; runner `agent-script-runner` @ `b1d1ee6`
**Verdict:** **PASS with one wiring gap (W-1)** — the four commits are sound and their
central claims are true at the source. `cap_result` has no production caller yet, so
task 3.2 is ticked ahead of its integration. That is a task-state question for the lead,
not a defect in the code that landed.

---

## Checked by execution, not by the builder's account

| Check | Result |
|---|---|
| `worker.js:147` drops the return value | **Confirmed** — `const { value: _discarded, ...wire } = result` at the one place a tick result is formed |
| `look.js` can spend a host call | **No** — zero references to `accept`/`__host`/`globalThis` in the file |
| `toGuest` invented helper | **Absent** — no such symbol; `look` is built from the imported `GUEST_SOURCE` |
| deep-copies prevent world-model edits | **Confirmed by mutant** — dropping `JSON.parse(JSON.stringify(...))` reds exactly `mutating a result does not reach the snapshot` |
| latin-1 mutant kills the validity test | **Confirmed** — 1 of 47 reds, and it is `test_the_cut_report_is_still_valid_text` |
| other self-round-trip tests in these commits | **None found** — no `encode().decode()` patterns; all new assertions discriminate |

## The builder's vacuity admission is honest and its claim is true

`ddaf29f` says the earlier 3.2 validity test was vacuous (`text.encode().decode()`,
which cannot fail) and was replaced. I ran the replacement's mutant rather than reading
the claim:

```
mutant: return raw[:RESULT_CAP_BYTES].decode("latin-1") + MARKER, True
FAIL: test_the_cut_report_is_still_valid_text
Ran 47 tests — FAILED (failures=1)
```

Exactly one red, and it is the test the commit names. The replacement asserts on **bytes**
(`raw.startswith(got)`, then `got.decode("utf-8")`), which is the property that actually
matters, not a str round-trip. Restored to a clean tree afterwards (diff empty).

This is the second time this builder has caught its own vacuous test and said so
unprompted. Worth noting as a pattern that is working.

## ddaf29f's delta says exactly what the lead decided

Read against the four-point decision, the spec text matches each:

- **(a) one of 8 host calls** — "MUST cost one of the tick's 8 host calls", with a scenario
  where one of the 8 is `api.result` and a clause that it "MUST NOT be free".
- **(b) capped by 3.2's marked cut** — "MUST be JSON-serialised and capped by the same
  2 KiB marked cut"; the size-cap scenario reworded from `returns` to `calls api.result`.
- **(c) last call wins, trigger unchanged** — "the LAST value MUST be the one kept", plus
  a scenario pinning the second call's value and that the first "MUST NOT appear". The
  trigger sentence is unchanged: done/error/escalate.
- **(d) no trigger by itself** — an explicit scenario: a script calling `api.result` that
  keeps ticking and never reaches done/error/escalate MUST raise no planner call.

**Can the two scenarios go red?** They are spec-first — task 3.1 is unticked and
`api.result` is not implemented (`grep` over `script_tick.py` finds no `api.result`), so
they cannot be *run* yet. As written they are falsifiable: "the delivered value MUST be
the second call's / the first value MUST NOT appear" is directly observable, and "no
planner call MUST be triggered" is a count over planner invocations. They pin behaviour,
not wording.

The delta's central justification is also true at the source: `worker.js:147` really does
destructure the return value off, and the surrounding comment records the 2026-11-10 rule.
So the commit is right that using the return value would have silently reversed a standing
decision — the reasoning holds.

## 5a25358 closes my N-1 and N-2

N-1: the block fixture now emits `{id, block, position}` and the contract test pins the
**exact key set** (`sorted(...) == ["block", "id", "position"]`), so a re-invented `type`
reds instead of drifting. Entities correctly keep `type` and a **string** `distance`
("4.2"), which is what the mod puts on the wire. This is the fix I asked for: the drift
was invisible because nothing pinned the shape.

N-2: task 1.1 now cites the four design-review commits that exist on `minecraft-wt-qwen`
rather than an `/egm-review` artefact absent from the tree. That is an honest citation.

## W-1 — `cap_result` has no production caller

`grep -rn cap_result --include=*.py` outside tests returns only its own definition at
`script_tick.py:52`. `tick()` does not call it. So task 3.2 ("[x] Size capped, truncated
with a marker rather than dropped") is ticked while nothing a script reports is actually
capped today.

The task note is careful — it says "`cap_result` in `script_tick.py`, 6 tests" and does
not claim it is wired — so this is arguably 3.2 being the *helper* half of a task whose
call site is 3.1. But the checkbox reads as user-visible behaviour that does not exist
yet. Two clean options:

1. Move 3.2's integration into 3.1 so the cap is applied where `api.result(v)` is
   stored, and reword 3.2 to "the capping helper, pending 3.1's call site"; or
2. Leave it and add one line to 3.2 saying the caller arrives in 3.1.

I recommend (1) — it makes the tick honest without creating a task for one line.

## Suites and validation, run bounded

| Run | Result |
|---|---|
| `python3 -m unittest test_script_tick test_snapshot` | **68 OK**, rc=0 |
| `test_script_tick` alone | 47 tests |
| runner `npm test` (`node --test`, 2 GiB cap, nice 19) | **165 pass, 0 fail**, rc=0 |
| `openspec validate script-lookups-and-results --strict` | **valid**, rc=0 |

The runner's declared suite was read from `package.json` (`node --test test/*.test.mjs`)
rather than assumed, per the repo-declares rule.

## Notes for the design's later stages

- The spec delta is against `bot-coded-agents`, which exists only as a change-delta target
  and has never been archived into `openspec/specs/`. Nothing to contradict, but worth
  remembering when this change archives.
- `look`'s radius constants are 5/16, matching `BotPlayer.java:619-620` and the corrected
  design. The file says the radius is the game's, not the caller's, with the
  "not-searched-that-far" distinction — that is the F1/F2 correction carried correctly
  into code.

Nothing built, pushed or deployed. No `ollama-l3` request, no pod exec, nothing in `ci`.
All mutants applied to a scratch copy and reverted; both trees verified clean by empty
`git diff` afterwards.
