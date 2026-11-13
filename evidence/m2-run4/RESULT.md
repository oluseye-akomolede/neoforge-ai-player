# M2 run 4 — PASS

**Verdict: the pass criterion is met.** A verbatim `dispatch:` line for
`STORE_ALL` carrying its seq, plus the mod-side effect. Six consecutive ticks,
zero refusals.

Captured 2026-11-13T05:29:56Z from pod `aibot-agent-test-6b65bdfc95-b8ll5`,
agent container, `kubectl logs --timestamps`. Raw log: `agent-full.log`.

## The evidence, verbatim

```
2026-11-13T05:29:45.079294141Z [Scout/script] 1 action(s) this tick
2026-11-13T05:29:45.079336691Z [Scout/script] dispatch: STORE_ALL seq=1 {'kind': 'STORE_ALL'}
2026-11-13T05:29:45.086451530Z [Scout/L1] Directive sent: STORE_ALL {} -> accepted (id=19)
2026-11-13T05:29:45.133891606Z [Scout/L1] Directive COMPLETED: {}
2026-11-13T05:29:47.238360160Z [Scout/script] 1 action(s) this tick
2026-11-13T05:29:47.238405502Z [Scout/script] dispatch: STORE_ALL seq=1 {'kind': 'STORE_ALL'}
2026-11-13T05:29:47.246188526Z [Scout/L1] Directive sent: STORE_ALL {} -> accepted (id=20)
2026-11-13T05:29:47.261023179Z [Scout/L1] Directive COMPLETED: {}
```

## Counts (computed from the log, not eyeballed)

| line | count |
|---|---|
| `Scout/script` ticks with an action | 6 |
| `dispatch: STORE_ALL` | 6 |
| `Directive sent: STORE_ALL ... accepted` | 6 |
| `Directive COMPLETED` | 6 |
| `refused action` | **0** |
| `not executed` | **0** |
| `Traceback` | **0** |

Every tick dispatched. The pre-run failure mode — `refused action: ... action
has no 'kind'` — does not appear once.

## What was deployed, and how it was verified

| half | value | how verified |
|---|---|---|
| image | `sha256:a9e75ad1b1efd22f9cc15f81662aa0865d068e92c555f034a0440bd0c9147c38` | Harbor `Docker-Content-Digest` for the index, agreeing with the push output; pod `imageID` read back = same |
| image contents | `script_tick.py` `fd212211839f…`, `agent.py` `d765915655cf…`, `action_binding.py` `728825f7ab11…` | hashed out of the image, equal to `git show 513b502:<path>`; reviewer computed the same three independently |
| ConfigMap | `scout.js` `1824967e200dab94…`, 5852 bytes | applied from `git show 6f8ad66:deploy/agent-scripts.yaml`; mounted file re-hashed **inside the pod** at `/srv/aibot-scripts/scout.js` |

Both in-pod checks ran before any goal was driven.

## One check of mine was wrong, and the hash is what settled it

My first in-pod check A grepped for `def generate_runner_actions` and returned
0 with exit 1. The function is `translate_runner_actions`
(`script_tick.py:68`). The zero was a bad query — a name I had misremembered —
not a missing function. The `sha256sum` of the mounted
`/opt/aibot-agent/script_tick.py` is the prover: `fd212211839f…`, the same hash
recorded in the plan from `513b502`.

## Rollback (not taken)

To restore the pre-run state: `set image` to
`sha256:d1513fa2d6ecab1b761fe692078e065b27324d8b05e15062380f55ed69da3f41`,
re-apply `cm.before.yaml` with `resourceVersion`/`uid`/`creationTimestamp`
stripped, restart, then re-read the in-pod digest. `deploy.before.yaml` and
`cm.before.yaml` in this directory were both read back and verified before the
run: the deployment at `d1513fa2…`, the ConfigMap at `838efd89…` / 4893 bytes.
