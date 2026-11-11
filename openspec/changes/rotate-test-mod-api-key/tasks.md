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
- [ ] 3.6 Restart the three consumers: `l2-mcp`, `minecraft-test-server`,
      `aibot-agent-test`. Wait for rollout completion on each.

## 4. Verify

- [ ] 4.1 Old key → mod returns **401** (via `aibot-api:3100`). This is the
      load-bearing check: it proves no holder was missed.
- [ ] 4.2 New key → mod returns **200**.
- [ ] 4.3 `l2-mcp` pod is Running and not restart-looping; its logs show no auth
      errors against the mod after the restart.
- [ ] 4.4 `aibot-agent-test` ticks successfully (bots active on TEST), proving
      the `agent-config` path carries the new value.
- [ ] 4.5 Record on the queue row: consumers restarted, the five results, and
      the new fingerprint (first 12 chars only).

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
