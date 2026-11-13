# Review — the three provenance hashes (54d12cf), and the live run 4 on TEST

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **The provenance gap I filed at e245e3b is closed, and closed better
than I asked. The live run is real and clean. One correction to the tally in
the builder's message — it undercounts, in the safe direction.**

I was told no reply was needed. There were two claims in it I could not confirm
from prose, so I checked both rather than accept them: the plan now carries the
hashes, and the image running on TEST is the reviewed tree. Checking was the
right call — my first three greps returned zeros that were all my own fault.

---

## 1. THE HASHES ARE IN, AND THEY ARE CORRECT

They pasted the three values into `M2-PLAN.md` at `54d12cf`. Verified against
the commit, not the working tree:

```
git show 54d12cf:openspec/changes/coded-agents/M2-PLAN.md | grep -Fc <hash>
fd212211839f08b0 -> 2 hits   (1444-ish digest table at :1507, narrative at :1483)
d765915655cf5e5a -> 2 hits   (:1508, :1484)
728825f7ab11351f -> 2 hits   (:1509, :1509 narrative)
838efd89 (control) -> 2 hits
```

The control matters: it proved the query could return a positive. I needed it,
because my first run of this check returned **0 for all four** — I was grepping
the working tree, and my HEAD is `e245e3b`, my own review commit, which does not
contain `54d12cf`. A zero on all four including the control is a broken
instrument, not four absences. Same shape as the builder's own near-miss on
`generate_runner_actions`.

The three recomputed from `513b502` match the plan byte for byte:

| file | from `git show 513b502:<path>` | in the plan |
|---|---|---|
| `agent/script_tick.py` | `fd212211839f08b08f59962796afe1dc28f74cb18827a12e3879463229229443` | same |
| `agent/agent.py` | `d765915655cf5e5ac52154009f3b81bfbe3a646f1692a5c34afe1c30a2e9d93d` | same |
| `agent/action_binding.py` | `728825f7ab11351f3880b3c6cae10a0db00a11ac2bed6fa0626e5e800c5c7d89` | same |

## 2. AND THE IMAGE ITSELF CARRIES THEM — THE JOIN I ASKED FOR

My finding was that the hashes were *asserted as recorded* but absent, so a
reader could only trust the sentence. The fix is stronger than that: the same
three values now come out of the running container.

```
kubectl -n minecraft-test exec aibot-agent-test-6b65bdfc95-b8ll5 -- sha256sum ...
/opt/aibot-agent/script_tick.py      fd212211839f08b0...9229443  MATCH
/opt/aibot-agent/agent.py            d765915655cf5e5a...a2e9d93d  MATCH
/opt/aibot-agent/action_binding.py   728825f7ab11351f...00c5c7d89  MATCH
```

So three things now agree: the rev `513b502`, the plan's table, and the bytes
in the pod. That is the check a rebuild would have been performed to earn, and
it is satisfied twice over — once by their `docker create`/`docker cp`, once by
my live `exec`. My no-rebuild call stands, and the record now lets a reader who
was not in the session re-run it.

## 3. THE LIVE RUN IS REAL — MEASURED, NOT QUOTED

The builder reported "six ticks, six dispatches, six accepted, six COMPLETED".
The live log says more than six. Full-log tally, from `kubectl logs` captured
whole (198 lines, 9657+ bytes) parsed locally:

```
dispatches  41
accepted    41   (id=19 .. id=59, contiguous: max-min+1 == n)
COMPLETED   41
ticks       41   ("1 action(s) this tick")
Traceback    0
"action has no kind"  0
refusals     0
unknown kinds 0
every dispatch: STORE_ALL seq=1
```

**The count grows on every read because the run is live** (37 → 38 → 41 across
three captures). So 41 is a floor as of this capture, not a total — the run had
not stopped. But the *shape* is what matters and it is clean at every snapshot:
one dispatch, one accept, one COMPLETED, one tick, no errors. The builder's
"six" was presumably an early snapshot; it is not wrong, only stale.

**`seq=1` on all 41 is correct, not a stuck counter.** From the producer
(`binding.js`): `resetTickState()` sets `state.seq = 0` at `:116`, and `accept()`
increments at `:143` on the first host call. One host call per tick ⟹ `seq=1`
every tick. I checked this rather than assume it, because 41 identical `seq`
values looks exactly like a counter that never resets, and the opposite defect
would be a real one.

**Ids contiguous 19→59** is the strongest signal: each directive got a distinct
mod-side id, so these are 41 separate round trips, not one action logged 41
times.

## 4. THE CONFIGMAP HALF

```
/ srv/aibot-scripts/scout.js   1824967e200dab94...89783ca7b22
```

Equal to the reviewed bytes at `6f8ad66`/`513b502`/`d669a93` and to the value
I verified in `REVIEW-D669A93.md §5`. The mounted script is the fixed one, not
the rolled-back `838efd89` broken copy.

## 5. WHAT I STILL DID NOT VERIFY

- **That 41 is the final count.** The pod was live and growing. Whoever closes
  run 4 should take the tally after the run stops.
- **That every tick's directive completed in the *mod*, not just in the log.**
  `Directive COMPLETED` is the agent's own line; I did not cross-read the
  server. Same axis I flagged before — agent-side green is not mod-side state.
- **Nothing about deployment.** The pod is already running; I ran no deploy,
  apply or rollout, and this review authorises none.

## Verdict

`54d12cf` closes the finding: three hashes recorded, correct against `513b502`,
and confirmed a third time from inside the running image. That is the provenance
chain made re-checkable by a stranger.

The live run on `aibot-agent-test-6b65bdfc95-b8ll5` is genuinely exercising the
script path — 41 dispatches, 41 accepted with contiguous mod ids, 41 COMPLETED,
zero refusals, zero Tracebacks. The `action has no kind` failure is gone, and
the pod's `script_tick.py` is the `513b502` one, so the pass is attributable to
the reviewed code and not to a lucky pod.

One correction, in the safe direction: the builder's "six ticks" undercounts a
run that is still going. Take the final number after it stops, and note that
`seq=1` on every tick is the correct value — not a stalled counter.
