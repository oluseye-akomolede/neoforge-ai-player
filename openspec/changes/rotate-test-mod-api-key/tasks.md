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
- [ ] 1.5 Review row raised and lead OK received. **Nothing below runs until
      both exist.**

## 2. Backup

- [ ] 2.1 Write both Secret objects to a single file **outside git**, mode 600,
      named with the timestamp. Verify the file is non-empty and parses as
      JSON before proceeding — a failed redirect leaves an empty file that
      looks like a backup.
- [ ] 2.2 Print only the file's path, size and mode. Not its contents.

## 3. Rotate

- [ ] 3.1 Generate 40 characters without printing them.
- [ ] 3.2 Assert the generated value is non-empty and 40 chars. Refuse to
      continue otherwise.
- [ ] 3.3 Patch `secret/mod-api-key` key `api-key`.
- [ ] 3.4 Patch `secret/agent-config` key `MOD_API_KEY` only — via a merge patch
      naming that one key, so the other 17 stay byte-identical. Confirm all 18
      keys are still present afterwards.
- [ ] 3.5 Confirm the new fingerprint matches across **both** secrets and
      differs from `902a001fdc05`.
- [ ] 3.6 Restart order, deliberately chosen (lead ruling): patch all three,
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

- [ ] 4.1 **The mod rejects the old key**: old key → **401** (via
      `aibot-api:3100`). This measures exactly one thing — that the *mod* is no
      longer authenticating the old value after its restart. It does **not**
      prove no holder was missed (see 4.3/4.4). A green 4.1 beside red 4.3/4.4
      is a failed rotation.
- [ ] 4.2 New key → mod returns **200**.
- [ ] 4.3 **LOAD-BEARING.** `l2-mcp` pod is Running and not restart-looping;
      its logs show no auth errors against the mod *after* the 401 window
      closes. This is what proves the client carries the new value. The mod
      cannot prove this: a client on the stale key gets a 401 from the mod that
      is indistinguishable, from the mod's side, from the old key being
      correctly retired.
- [ ] 4.4 **LOAD-BEARING.** `aibot-agent-test` ticks successfully (bots active
      on TEST), proving the `agent-config` path carries the new value. Same
      reason as 4.3 — it is a client, not a verifier.
- [ ] 4.5 Record on the queue row: consumers restarted, the five results, the
      **measured** downtime, and the new fingerprint (first 12 chars only).

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
