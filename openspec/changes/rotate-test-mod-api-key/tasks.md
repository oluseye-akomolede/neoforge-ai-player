# Tasks

**Output rule for every step below:** print only set/unset, length, and the
first 12 chars of a sha256 fingerprint. Never `-o jsonpath={.data}`. Never the
value. This rule exists because breaking it is what created this change.

## 1. Plan (this document) — awaiting review and lead OK

- [x] 1.1 Enumerate every holder of the old value by **fingerprint**, across all
      Secrets and ConfigMaps in `minecraft-test`, not by name. Found two
      (`mod-api-key/api-key`, `agent-config/MOD_API_KEY`) serving three
      deployments. Proven the scan sees non-empty objects, so an empty result
      would mean absence rather than a broken query.
- [x] 1.2 Confirm the prod key in `ns minecraft` is a different fingerprint
      (lead check). Rotation must not touch it.
- [x] 1.3 Establish the startup-read behaviour: `apiKey` is `final`, set in the
      constructor, so a restart is required per consumer.
- [x] 1.4 Note the empty-key-disables-auth hazard and require a non-empty
      40-char value before patching.
- [x] 1.5 Review row raised and lead OK received. **Nothing below runs until
      both exist.**

## 2. Backup

- [x] 2.1 Write both Secret objects to a single file **outside git**, mode 600,
      named with the timestamp. Verify the file is non-empty and parses as
      JSON before proceeding — a failed redirect leaves an empty file that
      looks like a backup.
- [x] 2.2 Print only the file's path, size and mode. Not its contents.

## 3. Rotate

- [x] 3.1 Generate 40 characters without printing them.
- [x] 3.2 Assert the generated value is non-empty and 40 chars. Refuse to
      continue otherwise.
- [x] 3.3 Patch `secret/mod-api-key` key `api-key`.
- [x] 3.4 Patch `secret/agent-config` key `MOD_API_KEY` only — via a merge patch
      naming that one key, so the other 17 stay byte-identical. Confirm all 18
      keys are still present afterwards.
- [x] 3.5 Confirm the new fingerprint matches across **both** secrets and
      differs from `902a001fdc05`.
- [x] 3.6 Restart order, deliberately chosen (lead ruling): patch all three,
      then restart **`minecraft-test-server` (the mod)**, then the two clients
      `l2-mcp` and `aibot-agent-test` immediately after.

      **The 401 window is accepted and must be stated, not hidden.** Between the
      mod restarting and each client restarting, that client still holds the old
      key while the mod holds the new one, so everything it sends fails 401. The
      window is short (the clients restart back-to-back) but it is real. A red
      flag in `l2-mcp` logs during that window is expected and is not a failed
      rotation.

      **What this step costs.** `minecraft-test-server` is the game server, not
      a sidecar. Restarting it drops and recreates the world session and takes
      TEST offline for the duration. Verified from the cluster, not assumed:
      - preStop runs `timeout 30 rcon-cli stop` (vanilla save-and-stop), then
        waits up to 180 s for the Server thread to exit, then TERM, 30 s, KILL.
        A normal stop therefore **saves the world**; no data loss.
      - `terminationGracePeriodSeconds: 300`, strategy `Recreate`.
      - **Measured startup on the current pod:** PodScheduled `04:33:55Z` →
        container started `04:34:15Z` → Ready `04:38:11Z`. That is **20 s**
        schedule→container and **3 m 56 s** container→Ready, so **4 m 16 s**
        schedule→Ready. Plan downtime around **4 m 16 s**; 3 m 56 s is boot
        alone and understates the outage by the 20 s before the container
        starts.
      - Expected total downtime: startup (measured **4 m 16 s** schedule→Ready)
        plus the stop (bounded by the hook: ≤30 s stop + ≤180 s thread wait +
        ≤30 s TERM = 240 s worst case).
        State the observed figure on the row when it actually runs; do not
        carry this estimate forward as a measurement.

## 4. Verify

- [x] 4.1 **The mod rejects the old key**: old key → **401** (via
      `aibot-api:3100`). This measures exactly one thing — that the *mod* is no
      longer authenticating the old value after its restart. It does **not**
      prove no holder was missed (see 4.3/4.4). A green 4.1 beside red 4.3/4.4
      is a failed rotation.
- [x] 4.2 New key → mod returns **200**.
- [x] 4.3 **LOAD-BEARING.** `l2-mcp` pod is Running and not restart-looping;
      its logs show no auth errors against the mod *after* the 401 window
      closes. This is what proves the client carries the new value. The mod
      cannot prove this: a client on the stale key gets a 401 from the mod that
      is indistinguishable, from the mod's side, from the old key being
      correctly retired.
- [x] 4.4 **LOAD-BEARING.** `aibot-agent-test` ticks successfully (bots active
      on TEST), proving the `agent-config` path carries the new value. Same
      reason as 4.3 — it is a client, not a verifier.
- [x] 4.5 Record on the queue row: consumers restarted, the five results, the
      **measured** downtime, and the new fingerprint (first 12 chars only).

## Results (run 2026-11-11, TEST only)

Plan revision executed: `ff32d68`; arithmetic and positive-control edits landed
at `6915b2a` before the run began. Downtime arithmetic was corrected to
schedule→Ready **4 m 16 s** (3 m 56 s is container start→Ready alone).

- Players online before the stop: **0 of 20**, so no in-game warning was needed
  and the lead's 2-minute hold did not apply.
- Backup: `~/.rotation-backup-20261111T115702Z.json`, mode `600`, 3937 bytes,
  parses, both secrets, `agent-config` intact at 18 keys, old fp `902a001fdc05`.
- Guard: generated value exactly 40 non-empty chars before patching.
- New fingerprint across **both** secrets: `3b0a18f8580c` (old was
  `902a001fdc05`). `agent-config` still 18 keys after the single-key patch.
- **Downtime measured:** `11:57:19Z` (rollout restart issued) → `12:01:53Z`
  (`rollout status` Ready) = **4 m 34 s**. That is restart→Ready, which includes
  the stop; it is not the same quantity as the 4 m 16 s schedule→Ready figure
  above and is not comparable to it term for term. Clients Ready `12:02:34Z`.

| Check | Result |
|---|---|
| 4.1 old key rejected | **401** on `/bots` with `X-Api-Key` |
| 4.2 new key accepted | **200** on `/bots` with `X-Api-Key` |
| 4.3 `l2-mcp` (LOAD-BEARING) | Running, restarts 0; in-container `MOD_API_KEY` fp `3b0a18f8580c`; no auth errors |
| 4.4 `aibot-agent-test` (LOAD-BEARING) | Running, restarts 0; in-container fp `3b0a18f8580c`; mod returned `status: ok`, 5 profiles, bots spawning |

**Probe defect found during the run, recorded because it nearly produced a false
rollback.** The first probes sent `Authorization: Bearer <key>` and 401'd for
*both* the old and the new key. The check is `X-Api-Key`
(`HttpApiServer.java:149-153`), so both were rejected on the header, not the
value. A second probe also 404'd against `/status`, a route that does not
exist. Either would have read as "the new key is broken" to anyone not checking
the auth code, i.e. as grounds to roll back a successful rotation. Both were
re-run against `/bots` with `X-Api-Key` and only those runs are quoted above.

Also note: `aibot-agent-test`'s pods carry `app=aibot-agent`, not
`app=aibot-agent-test`. A pod query on the obvious label returns empty and is
indistinguishable from a dead deployment.

Probe Jobs and the temporary old-key Secret were deleted; `get job,secret`
confirms none remain.

## 5. Rollback (only if verify fails)

- [ ] 5.1 Re-apply the backup file over both secrets.
- [ ] 5.2 Confirm the fingerprint returns to `902a001fdc05`.
- [ ] 5.3 Restart the same three consumers.
- [ ] 5.4 Record the rollback on the row with the reason.

## 6. Close out

- [ ] 6.1 Archive this change once verified.
- [ ] 6.2 Delete the backup file only after the lead confirms they no longer
      want the rollback path. Deleting it while the old key may still be in
      use would be the one cleanup that cannot be undone.
