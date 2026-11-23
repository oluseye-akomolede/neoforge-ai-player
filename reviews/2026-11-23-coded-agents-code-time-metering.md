# Review — coded-agents 5.1 + 5.5, per-bot code-time metering (5619b0a)

**Verdict: PASS with one finding (F-1).** The metering is correct for the
scenario it claims — an active, sent tick accrues one period; a held script
accrues nothing; usage is per bot; a dry tick is not metered; 1800 ticks is
one hour; the cap is unlimited — and it is placed at the one non-dry send
point, below the hold early-return. F-1 is an over-claim in the prose, not a
defect in the mechanism, and does not block.

Reviewed rev: `5619b0a406f8f7c228986ccf998741e8835f0951` (`ship-ca27-harness`,
parent `e8b2701`). Row `qitem-20261123001944-585298fdb9f15885`, scope option
(3) metering only: 5.1 and 5.5. 5.3/5.4 (cap value, enforcement) are out of
scope by the lead's decision and are NOT reviewed here.

Everything below was run by me from a clean `git archive 5619b0a` into
`/tmp/ct-probe`, not read out of the builder's worktree.

## What I verified

**The counter's arithmetic.** `CodeTimeMeter` has one mutator, `record_tick()`,
adding `_tick_period` — imported from `config.TICK_DELAY` (2.0 s), not
re-declared, which is right: the meter must use the number the loop waits.
`usage_hours = seconds/3600`, `tick_count` kept beside it.

**The suite, and that it depends on the call.** `python3 -m unittest
test_code_time` → `Ran 8 tests ... OK`; with `test_agent_script_branch` →
`Ran 149 tests ... OK`. Mutants, each applied as an exact single-site replace:

| mutant (what it removes) | result |
|---|---|
| `agent.py`: the `_record_code_time_tick()` call → `pass` | 3 ERROR (AttributeError) — red |
| `code_time.py`: `self._seconds += self._tick_period` → `+= 0` | 4 FAILED — red |
| `code_time.py`: `is_exhausted` returns `False` unconditionally | 0 red — **survives** |

The surviving mutant is not a gap in *this* row (see F-2): with the cap
hardwired `UNLIMITED`, `is_exhausted()` returns before reaching that line in
every deployment, which the docstring says outright.

**Placement.** `_run_script_tick` (`agent.py:3707-3731`) returns
`SCRIPT_HELD` at the hold check before the call; the dry path is
`_dry_tick` (`:3944`), a different method that builds its own `dry=True`
`ScriptTick` and returns before the caller's line. `_get_script_tick()` gates
`None` on no-script and on `_script_halted_for_stop`, so neither reaches the
meter. Meter is created in `__init__` and lazily in `_record_code_time_tick`,
so `__new__`-built test runners work — I exercised that path.

**What I did not run.** The Java suite and a live runner are out of scope for
this row (the meter is agent-side only); I did not deploy or drive a bot.

## F-1 — the claim of what "accrues nothing" covers is wider than the code

> **CLOSED at `ba57b33`** (see "F-1 follow-up" at the end). The finding below
> describes `5619b0a` and is kept as the record of what was wrong.

The commit message, `code_time.py`'s docstring and the "DONE" text in
`tasks.md` 5.1 all say a **"held, paused, disabled, deleted or fallen-back
script accrues nothing"**, and the module's docstring explains it as *"the
counter is fed only at the send point, so time a script spends … accrues
nothing — because no tick is sent for any of those"*.

That is true for held and halted-for-stop (`_get_script_tick` returns `None`).
It is **not** true for a tick the runner refuses. `ScriptTick.tick()` returns
`False, [], [], f"runner {state}: {detail}"` on every non-`script` state
(`fallback_timeout`, `fallback_refused`, `fallback_error`), `_run_script_tick`
does not branch on that tuple, and `_record_code_time_tick()` sits
**unconditionally after it** — so a refused or timed-out tick counts.

Measured through the real `_run_script_tick` at `5619b0a` (probe:
`/tmp/ct-probe-probe.py`, the stub returns exactly the tuple
`script_tick.py` produces for a refused tick):

```
ok-tick        returns=False  meter=(1, 2.0)
refused-tick   returns=False  meter=(1, 2.0)      <- counted
10x refused    returns=--     meter=(10, 20.0)    <- 20 s for zero script work
```

Reachability: a bot in `SCRIPT_BOTS` is bound (`bindings.json` is a ConfigMap,
the binding survives a runner outage), and `_build_snapshot` does not gate on
its `errors`, so the tick is sent every 2 s whether or not the runner answers.
An unreachable or erroring runner therefore meters a bound bot at the full
rate while the planner takes every tick.

**Against the spec**, the requirement is *"The cap therefore measures, and can
only measure, **active** time"* and *"the game MUST count each tick it sends"*.
A refused tick is sent, so counting it is a defensible reading — but it is NOT
the reading the code's prose gives, and for a `fallback_timeout` the "tick"
was not an active script's tick at all (the runner accepted the connection and
did not answer within 0.3 s). Whoever turns the cap on (5.4) will believe
"non-active ⇒ free" and find out otherwise from a bill.

**Scope of the claim I make.** I did not measure this against a live runner;
I measured the caller's behaviour given the tuple the refused path returns,
which is the whole of the decision. **Recommendation:** either narrow the prose
to what `_get_script_tick` actually gates (held, halted-for-stop, no-script),
or move the call to where the outcome is a `script` result
(`result.state == STATE_SCRIPT`), which is a 5.4-sized decision. I would take
the prose fix in this row and let 5.4 decide whether refused time is billed.
Not a blocker: the cap is unlimited, so today this meters time nobody is
charged for.

## F-2 — `is_exhausted()` is untested where it could fire

The surviving `return False` mutant above. The test
`test_cap_is_unlimited_and_never_exhausts` pins the unlimited path only, which
is right for 5.5 but means the one branch 5.4 will rely on has never run.
Recorded as a note for 5.4's review, not a defect of this row.

## Reported-and-not-chosen (the builder flagged both; I agree)

The **day boundary** and **restart persistence** are silent in the change spec.
`usage_hours()` is a process-lifetime total and a restart zeroes it. I checked
the spec's own language: "hours/day" and "daily cap" presuppose a day, and no
reset exists anywhere in `code_time.py`. That is a real unstated decision, and
the right handling is the one used here — report it, do not invent it. **My
answer to the builder's question: neither should block this row.** But the day
boundary is a precondition for 5.4, not just for 5.3: a cap compared against a
total that is neither daily nor persisted cannot do what "cap" says. It should
go to the lead as a question for the owner before 5.4 is built, not after.

## Also checked

- **spec.md:123 correction** (`"the game drives the tick"` → `"the Python agent
  drives the tick"`) is accurate: `_loop` calls `_run_script_tick` and waits
  `TICK_DELAY`; the Java mod has no script path. Matches what I established in
  the world-clock review. Good catch by the builder.
- **Line cites**: `agent.py:3731` is the metering call at this rev; `:3944` is
  `_dry_tick` (the commit says `:4009`, which was the pre-change rev's number —
  harmless, the name is there). `spec.md:487` is the requirement heading.
- **Per-bot, never summed**: one `CodeTimeMeter` per `BotRunner`; no aggregate
  exists on any shared surface. Measured by the two-runner test.
- `openspec validate coded-agents --strict` — I did not re-run it; the diff
  ticks 5.1 and updates no requirement text except the :123 row.

## Not done, stated plainly

- Nothing pushed, nothing deployed, no cluster touched, no live bot driven.
- I did not run a refused tick against a live runner (no sandbox); see F-1's
  scope note for exactly what that leaves unmeasured.
- 5.3/5.4 not reviewed (out of this row's scope).

## F-1 follow-up — closed at `ba57b33` (verified from a clean archive)

Diff `5619b0a..ba57b33` is 3 files, +23/−8: `agent/agent.py` (the `__init__`
comment), `agent/code_time.py` (module docstring and `record_tick` docstring),
`openspec/changes/coded-agents/tasks.md` 5.1. **No code line changed** — every
hunk is inside a comment or `"""…"""`. Confirmed by reading the diff, not by the
commit message.

The prose now says what the code does at all three sites: held / paused /
deleted / fallen-back accrue nothing *because no tick is sent*, and **a tick the
runner refuses or times out on does reach the counter and is billed one period**,
with billability named as 5.4's call. That is exactly the narrow reading F-1
proposed, and it matches my measurement.

One wording change worth recording: the old text said "held, paused, **disabled**,
deleted or fallen-back"; the new text drops "disabled" rather than asserting what
gates it. I had not measured the disabled path and did not test it here, so I
neither endorse nor contest that omission — it is the honest choice over a claim
nobody checked, and nothing else in the change depends on it.

Re-ran at `ba57b33` from `git archive` into `/tmp/f1chk/t` (prose-only, so this
is a no-regression check, not a new proof of behaviour):

```
cd /tmp/f1chk/t/agent && python3 -m unittest test_code_time
                        ... Ran 8 tests ... OK            rc=0
cd /tmp/f1chk/t/agent && python3 -m unittest test_code_time test_agent_script_branch
                        ... Ran 149 tests ... OK          rc=0
```

My first attempt at this used `-s agent -t .` from the archive root and died with
`ImportError: Start directory is not importable: '…/agent'` — `agent/` is not a
package. The tests are written to run with `agent/` as the cwd; run them that way
or you get an error that looks like a red suite. Recorded because it cost a round
trip and will cost the next person one too.

**Verdict on F-1: closed.** Nothing was pushed or deployed for either commit.

## Repro

```
git archive 5619b0a | tar -x -C /tmp/ct-probe
cd /tmp/ct-probe/agent && nice -n 19 python3 -m unittest test_code_time          # 8 OK
cd /tmp/ct-probe/agent && nice -n 19 python3 -m unittest test_code_time test_agent_script_branch  # 149 OK
nice -n 19 python3 /tmp/ct-probe-probe.py /tmp/ct-probe/agent                    # refused tick still counts
# mutant: replace the _record_code_time_tick() call with `pass` -> 3 ERROR
```
