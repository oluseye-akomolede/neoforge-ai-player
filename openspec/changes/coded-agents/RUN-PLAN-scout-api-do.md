# Run plan — scout.js emits via `api.do` (M2 §8.3)

Commit under test: `096c1e9`. Reviewer PASS is required before step 3.

This replaces the script half only. The runner fix (image `sha256:6e079944…`)
is already live and is not touched here.

## What changes

One file reaches the cluster: the `agent-scripts` ConfigMap, whose `scout.js`
entry becomes the version that calls `api.do`.

| | live now | after |
|---|---|---|
| `agent-scripts` `scout.js` sha256 | `838efd891994f434511913b0225b43587a54ba6b281ae7b4bc4c13951bbb9344` | `1824967e200dab94bb02108c0dfa84584f070007ce2cc0eab0b0a89783ca7b22` |
| `bindings.json` | `{"Scout": "scout.js"}` | unchanged |

Read from `kubectl -n minecraft-test get cm agent-scripts -o jsonpath='{.data.scout\.js}' | sha256sum`
on 2026-11-13. The deployment mounts it as `scripts -> agent-scripts`
(`configMap` volume).

**No image rebuild.** `scout.js` is delivered by the ConfigMap precisely so a
script change does not need one.

**A pod restart is required regardless.** `_script_loaded` caches the script
once, at the first `_get_script_tick()` call, and never re-reads it, so a
ConfigMap update alone changes nothing the running pod sees.

## Steps

1. **Back up the live ConfigMap** (the rollback source):
   ```
   kubectl -n minecraft-test get cm agent-scripts -o yaml > /tmp/agent-scripts.bak.yaml
   ```
   Verify it contains both keys and the digest above before continuing.

2. **Apply the generated ConfigMap**:
   ```
   kubectl apply -f deploy/agent-scripts.yaml
   ```
   Then re-read the digest and confirm it equals `1824967e200dab94bb02108c0dfa84584f070007ce2cc0eab0b0a89783ca7b22`. If it
   does not, stop: the cluster is not running the reviewed bytes.

3. **Restart the agent pod** (required — see the cache note above):
   ```
   kubectl -n minecraft-test rollout restart deploy/aibot-agent-test
   kubectl -n minecraft-test rollout status deploy/aibot-agent-test --timeout=300s
   ```

4. **Verify the pod mounted the new script**, not the old one:
   ```
   kubectl -n minecraft-test exec deploy/aibot-agent-test -c agent -- \
     sha256sum /srv/aibot-scripts/scout.js
   ```
   Expected: `1824967e200dab94bb02108c0dfa84584f070007ce2cc0eab0b0a89783ca7b22`. This is the check that would have caught the
   earlier stale-ConfigMap incident, where the image was right and the mounted
   script was not.

5. **Verify the script now acts** — the pass criterion, and it must be an
   observed action, not silence:
   - Drive a goal through the mod's chat injection so a script tick has a bot
     that can act (`POST /bot/Scout/chat` inside the pod; key never on a
     command line).
   - The evidence is a tick whose collected `actions` is **non-empty and names
     `STORE_ALL`**, quoted verbatim.
   - Scout carries 16 cobblestone and a chest exists at (16, 99, -15), so a
     `STORE_ALL` has something to do. If the script legitimately holds, say
     which guard and why — holding is not a pass.

6. **Confirm no regression in the control**: the planner path is unaffected
   (this change touches only the script), so the §8.3.4 control baseline
   should be unchanged. Re-take it rather than assume.

## Rollback

```
kubectl apply -f /tmp/agent-scripts.bak.yaml
kubectl -n minecraft-test rollout restart deploy/aibot-agent-test
kubectl -n minecraft-test rollout status deploy/aibot-agent-test --timeout=300s
```

Then re-read the ConfigMap digest and confirm it is back to `838efd89…`. The
rollback is complete when the mounted file matches, not when the apply returns.

## Known risks

- **The pod restart interrupts all five bots**, not just Scout, for roughly the
  restart window (~30-60 s). Announced to cardgame-lead because the runner and
  this cluster are shared.
- **`scout.js` was verified by direct tick on the live runner**, not yet by the
  agent's own loop. Step 5 is the first loop-driven evidence; if it does not
  appear, that is a finding, not a retry.
- **The L3 planner separately emits directive kinds the mod does not know**
  (`SEARCH_AND_STORE`, `SEARCH_AND_MINE`), so a plan can finalise "complete"
  with zero actions. Tracked on row `qitem-20261113044039-b3150175db2d35fc`.
  It does not block this run, but it will make the control look like a no-op.
