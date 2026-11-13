# M2 run 3 — the `api.do` fix deployed, and the defect it exposed

**Outcome: the pass criterion was NOT met. The run failed and was rolled back.**

This run did what it was supposed to do: it put the reviewed `scout.js` in front
of the real agent loop for the first time, and in doing so it found the next
layer of the same defect. Recording it here because the second half is worth
more than the first.

## What was deployed, and how it was verified

| | value |
|---|---|
| rev applied | `6f8ad66`, `deploy/agent-scripts.yaml` piped to `kubectl -n minecraft-test apply -f -` |
| `scout.js` before | `838efd89…` (4893 bytes) |
| `scout.js` after | `1824967e…` (5852 bytes) — byte-identical to `6f8ad66:agent/scripts/scout.js` |
| verified in-pod | `sha256sum /srv/aibot-scripts/scout.js` → `1824967e…` in pod `aibot-agent-test-58db469b88-pw6q7` |
| backup | `~/m2-run3-agent-scripts.bak.yaml`, 4893 bytes, `838efd89…` confirmed before the apply |

The deploy itself was correct at every checkpoint. The fix reached the running
pod — the step that failed in the earlier stale-ConfigMap incident.

## What happened: the script fired, and was refused

Within the first ticks after the restart, the agent loop began printing, twice
per tick:

```
[Scout/script] refused action: {'index': 0, 'kind': None, 'error': "action has no 'kind': {'seq': 1, 'call': 'do', 'directive': 'STORE_ALL', 'args': {}}"}
[Scout/script] falling back to planner: all actions refused
```

Timestamps from the run (verbatim, `kubectl logs -c agent --timestamps`):

```
2026-11-13T05:15:30.927916822Z [Scout/script] refused action: ...
2026-11-13T05:15:30.927957576Z [Scout/script] falling back to planner: all actions refused
```

**This is the fix working, not failing.** Before the fix, the script returned an
array the engine discarded and `actions` was empty — Scout was silent. Now the
script calls `api.do("STORE_ALL", {})`, the runner collects it, and the record
reaches the agent. The action is proposed. It is then refused one layer later.

## The defect: two names for one field, never compared

**Producer** — `agent-script-runner/src/binding.js:243-250`. `api.do` pushes:

```js
state.actions.push({ seq: state.seq, call: "do", directive, args });
```

The field is **`directive`**. The runner validates shape only and deliberately
does not validate the name against the game's vocabulary (§4.1).

**Consumer** — `agent/action_binding.py:81`. `bind_action` reads:

```python
raw = action.get("kind", action.get("action"))
```

It knows **`kind`** and **`action`**. Not `directive`.

`agent/script_tick.py:179` passes `result.actions` straight into
`bind_actions(...)` with no translation between them, so the two names meet
directly and one of them is always wrong.

## Why no test caught it

`agent/test_action_binding.py` only ever feeds fixtures shaped `{"kind": ...}`.
Grepping it for the runner's record shape (`seq`, `call`, `directive`) returns
nothing. Every test in that file agrees with the consumer's assumption; nothing
compares it to what the producer emits.

This is the same class as the original `scout.js` bug — a check written from
what the consumer expects rather than what the producer sends — and the same as
`test_scout_script.py` rewriting the artefact before asserting on it. The
earlier fixes are what made this one visible: with the script silent, nothing
ever reached the binder.

## Rollback

The lead's instruction was roll back and report. Done, and verified:

| | value |
|---|---|
| command | cleaned backup applied (see note), `kubectl -n minecraft-test apply -f -` |
| `scout.js` after | `838efd89…` |
| pod | `aibot-agent-test-7554db5447-8f8bh`, mounted `838efd89…` |
| refusal lines after | 0 |

**A note on the first rollback attempt, since it failed.** Applying the backup
YAML directly was rejected:

```
Operation cannot be fulfilled on configmaps "agent-scripts": the object has
been modified; please apply your changes to the latest version and try again
```

The backup carried the `resourceVersion` from when it was taken, and my own
apply had moved the object on. Re-applying it would have been a no-op that
looked like a rollback. Stripping `resourceVersion`/`uid`/`creationTimestamp`
and re-applying succeeded. **A backup taken as `-o yaml` is not directly
re-appliable once the object has changed** — worth knowing before the next run.

## What is NOT claimed

- The pass criterion (a verbatim tick with `STORE_ALL` in its actions) was not
  met. No `dispatch:` line was ever printed for this run.
- The control arm (§8.3.4 run 1) was not taken. The run failed on the script
  arm before the control became relevant.
- Nothing about the fix's correctness is retracted. `scout.js` now emits via
  `api.do` and is collected; the refusal is downstream of it.

## The fix this implies (not made — needs direction)

Either the binder must accept `directive` as the record's kind field, or the
runner/client must translate `directive` → `kind` at the boundary. Which one is
right is a contract question for the lead, not something to settle by patching
whichever file is closer. The test that would have caught it either way is one
that feeds the runner's **emitted** record into `bind_actions` — not a
hand-written fixture.
