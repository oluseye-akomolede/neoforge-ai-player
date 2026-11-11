# TEST rcon password rotation — plan

Queue row: `qitem-20261111132431-68296d029b524fca` (superseded shape by
`qitem-20261111135857-fce29a3b`, lead 13:58Z/13:59Z).

**Why.** The TEST rcon password was printed into the builder transcript at
13:2xZ while checking whether rcon was enabled, and that transcript is sent to
the DeepSeek API. TEST publishes rcon as a **NodePort**, so on the LAN the
password is the only barrier. The value is compromised and must be treated as
public.

**Scope.** `minecraft-test` only. Prod is a different value (lead checked by
fingerprint) and is not touched by anything here.

**Rule for this whole document.** No credential value appears anywhere below —
only lengths and sha256 fingerprints. No command here prints one. Where a
command must handle the value, it goes through a shell variable and is never
echoed.

---

## 1. Every holder of the current value

Found by scanning values, not names: a fingerprint match against
`sha256(current)[:16]`, across Secrets, ConfigMaps, Deployment env and every
file on the data volume.

**The fingerprint is deliberately not written in this document.** It is 64 bits
of the credential this rotation exists to close, and publishing it here would
give anyone a cheap way to check a guess. The value is printed at execution
time into the run log instead, where a run log belongs. The forward scan — how
the next holder is found — is in section 5.

**Positive control.** The scan was validated by requiring it to re-find the
Secret it started from. It did (`positive control: True`). Without that, a zero
would not have meant anything — the same-shaped scan that produced the earlier
false pass.

| # | Holder | Location | How it carries the value |
|---|---|---|---|
| 1 | Secret `minecraft-rcon` | key `password`, 32 bytes | consumed by Deployment env `RCON_PASSWORD` via `secretKeyRef` |
| 2 | `/data/server.properties` | line `rcon.password` | the server's own runtime copy on the PVC |

Both holders match one another by fingerprint (recorded on the row and printed
at execution time, never here). Nothing else assigns `rcon.password`: the 400+
`.bak` and mod-config files on the volume were scanned **by value**, not by
name, and none match. That scan includes the `.bak` files — they are part of
the scanned set in this section, not a separate claim in the table.

**Deployment env.** `RCON_PASSWORD` is a `secretKeyRef` to
`minecraft-rcon/password`, not a literal. So rotating the Secret covers the
container's environment; `/data/server.properties` is rewritten by the server
from that env on start, but it also exists independently and is holder 2.

**Consumers** (who uses the value, and so what breaks during rotation):

| Consumer | Where | Path |
|---|---|---|
| In-cluster: any workload using rcon | `minecraft-test` | `minecraft-test-server:25575` |
| External: operator / tools | LAN | Node `:31167` → svc `:25575` |
| The server itself | pod | reads env → writes `server.properties` |

**Open question for the lead, not acted on:** does TEST need rcon published as
a NodePort at all? Listed here as the row requires; the decision is the lead's.
Dropping `:31167` would leave the service reachable in-cluster only.

---

## 2. Value handling

- New value generated **in place**: `head -c 24 /dev/urandom | xxd -p -c 48`
  gives exactly **48 hex characters**, held in a shell variable, never echoed,
  never written to a file on this VM. Hex is chosen deliberately: it cannot
  produce `/`, `+`, `=` or a newline, so there is no escaping question in the
  Java properties file and none in `kubectl --from-literal`. A base64 pipeline
  was the first draft and was wrong — `head -c 32 | base64` emits 44 characters
  and "sliced to 32" never said which 32.
- Refuse an empty value, or a length other than 48, before writing anything.
  The length is the acceptance test, so the derivation above is what makes that
  test meaningful rather than decorative.
- **No backup of the old value.** It is compromised; a backup that restores it
  is a way to put the public password back. This is the one rotation where
  "we can roll back" is the wrong instinct — roll **forward** with a new value
  if something breaks.
- After the write, verify with `pytest`-free checks: new value works, old value
  is refused, both holders carry the new fingerprint.

---

## 3. Order

Downtime is one server restart. Check for online players first and stop if
anyone is connected, unless the lead says otherwise.

1. **Pre-checks.** Record the current fingerprint of both holders; confirm they
   match each other (they should — if not, stop and report, because a mismatch
   means a third path is writing one of them). Count online players; a non-zero
   count stops the plan pending the lead's word.
2. **Rotate the Secret.** Generate, validate length 48 (section 2), `kubectl create secret
   ... --dry-run=client -o yaml | kubectl apply -f -`. Value never printed.
3. **Restart the server** so the env re-reads and `server.properties` is
   rewritten: `kubectl rollout restart deploy/minecraft-test-server`.
4. **Rewrite `/data/server.properties`** if the server did not: set
   `rcon.password` to the new value in-pod from the Secret, without printing it.
5. **Verify.** (a) rcon with the new password → a real command returns a reply;
   (b) the old password is refused; (c) both holders fingerprint to the new
   value; (d) the deployment is Ready and the server accepts players.
6. **Report** fingerprints and lengths only.

---

## 4. Rollback

There is no value rollback by design (§2). If step 5 fails:

- If the **server will not start** with the new value, the fault is in the
  write, not the value: re-apply the Secret from the same generated value,
  restart, and re-verify. Rolling back to the old password is not an option.
- If the **old password still works**, the rotation did not take: a holder was
  missed. Re-run §1's value scan before retrying, because a surviving old value
  means a holder outside this table.

---

## 5. Out of scope

- Prod. Different value, untouched.
- Dropping the NodePort — listed in §1, decided by the lead after this lands.
