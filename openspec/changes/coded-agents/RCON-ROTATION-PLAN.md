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
| 3 | `/data/.rcon-cli.env` | key `password` | **derived** — written from `$RCON_PASSWORD` on every start (`start-configuration:87`) |
| 4 | `/data/.rcon-cli.yaml` | key `password` | **derived** — written from `$RCON_PASSWORD` on every start (`start-configuration:88`) |

All four match one another by value fingerprint (recorded on the row and printed
at execution time, never here).

**Holders 3 and 4 were missed by the first version of this section, and that
version was reviewed and PASSED.** It reported two holders and stated that
"nothing else assigns `rcon.password`". The scan that supported that claim
looked at `.bak` and mod-config files **by name and extension** — and the two
missers are dotfiles with no extension, so the file set never contained them. A
scan whose file set is chosen by a name pattern cannot find a holder the pattern
does not describe, and a zero from it is not an absence.

The corrected scan takes **every** regular file under `/data` outside
`world/`, `libraries/` and `cache/` — 1168 files on the day it ran; the volume
held 2221 in total after the restart — reads the value once into a shell
variable, and greps each file for it. That is the scan the numbers above come
from. Its positive control: the same command finds `/data/server.properties`
when given the string `rcon.password=`, so a hit reporting zero would be visible.

A file count in this document is a *measurement on a date*, not a property of
the volume: `/data` grew by more than a thousand files across the rotation's own
restart. Quote the scan's scope as what it enumerated, never as a fixed number
to re-check against.

**This is the failure §4 names.** Rotating with the old table would have left
two files carrying the old public password on the PVC; §5(a)-(b) would have
passed (the Secret and `server.properties` rotate correctly) while the old value
survived on disk. Checking only the paths the plan already knew about is what
would have made it pass.

**Two errors, not one, and they are worth separating.** The first was the scan
missing the files. The second came *after* I found them: I wrote that they were
"operator convenience files nobody declared" and proposed deleting them. That
was an inference from absence-in-my-table dressed as a finding -- exactly the
error class this document exists to avoid, committed in the same section about
looking properly. What settled it was checking the mtime against the pod start
(21 s after, two files 15 ms apart) and then reading the generator at
`start-configuration:87-88`. Had the delete been executed, it would have removed
two files the image rewrites anyway and left the appearance of having cleaned
something up. **Absence from your inventory is not absence of an owner.**

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
  is refused, all four holders carry the new fingerprint.

---

## 3. Order

Downtime is one server restart. Check for online players first and stop if
anyone is connected, unless the lead says otherwise.

1. **Pre-checks — and capture the search key 5(c) will need.**
   (i) Record the current **fingerprint of all four holders**; confirm they all
   match each other. If they do not, stop and report: a mismatch means some
   holder is being written from a source outside this list, and that source is
   the thing to find before rotating. (This said "both holders" when the table
   had two rows. With four rows, "a third path" is the wrong inference — two of
   the four *are* named, so an operator reading it literally would record two
   fingerprints and never see a mismatch among the others.)
   (ii) **Read the current value into a shell variable in the operator's session.**
   Something like `OLD=$(kubectl -n minecraft-test get secret minecraft-rcon
   -o jsonpath='{.data.password}' | base64 -d)` — never echoed, never written to
   a file, never on a command line `ps` can see. This is the **only** copy, and
   it must not outlive the rotation; 5(c) consumes it and the session ends.

   **Those three are not sufficient, and this is the trap in this step.**
   **`set -x` defeats all three at once.** The shell traces the *assignment*, not
   an echo, so nothing an operator sees looks like a print:
   `++ base64` / `+ OLD=U0VDUkVUVkFMVUU=`. That traced line is the value, and
   `base64 -d` decodes it trivially — **the encoding does not make the traced
   form safe.** An operator with xtrace on, a `script(1)` capture, or a CI runner
   that sets it has written a recoverable copy for the compromised credential to
   a log, which is the backup §2 forbids in the one place this plan had not
   looked. An operator who believes they are complying will not think `set -x`
   contradicts "never echoed", so it has to be said here.

   So every assignment and use of `OLD` runs with tracing and history off, and
   the shell's **prior** state is restored afterwards rather than assuming it was
   off (`set +x` would silently change an operator's environment, and an operator
   who normally runs traced would carry on believing they still were):

   ```
   # RUN THIS UNDER BASH. `set +o history` is a dash error ("Illegal option"),
   # so under `sh` this block does not quietly skip the history guard -- it dies
   # on that line with `set -e`, before the value is ever assigned. That is the
   # safe direction, but it fails for a reason an operator will not read as
   # "wrong shell". Caught by dry-running the script before it touched a cluster;
   # the plan as written named no shell at all.
   _xt=$(case $- in *x*) echo on;; *) echo off;; esac)   # remember, do not assume
   _hf=${HISTFILE+x}                                     # set-or-unset, not empty
   _hv=${HISTFILE-}
   set +x +o history; HISTFILE=/dev/null
   OLD=$(...)
   ... every use of $OLD ...
   [ "$_xt" = on ] && set -x
   if [ -n "$_hf" ]; then HISTFILE=$_hv; else unset HISTFILE; fi
   unset _xt _hf _hv
   ```

   **`${HISTFILE+x}` and not `${HISTFILE-}`.** An empty `HISTFILE` and an unset
   one need different restores, and `-` cannot tell them apart: with `-`, an
   operator whose `HISTFILE` was *originally unset* gets `[ -n "" ]` false, the
   restore is skipped, and `HISTFILE` is left at `/dev/null` for the rest of the
   session — the shell silently stops recording history. No credential leaks that
   way, but it is the guard committing the exact error it exists to prevent,
   assuming a prior state instead of restoring it. Measured, not reasoned: the
   old form left `HISTFILE` SET to `/dev/null` where it had been unset. The last
   line clears the three guard variables themselves, so the session is left as
   the operator had it rather than as this step needed it.

   **What the guard does not cover.** It brackets assignments and uses of the
   value *inside* the guarded region. A value that is already in an **argument**
   is traced before the region opens: measured, an outer `set -x` on
   `script.sh "$VAL"` prints `+ script.sh SECRETVALUE` with the guard working
   perfectly underneath it. So the value must never be passed as an argument to
   the guarded script — read it from the Secret inside the region, or hand it to
   the container on stdin. Passing it in argv defeats the guard by going around
   it, not through it.
   This clause belongs beside "never echoed" on purpose: it is the sentence that
   is true and still not enough.
   Why this step exists at all: **a fingerprint cannot be grepped for.** The
   files hold the value, not its hash. Before this clause, 5(c) asked for a scan
   for the old value at a moment when step 2 had already overwritten the Secret
   and §2 forbids keeping a backup — so the search key was guaranteed absent and
   the step that exists to catch a missed holder could not have run.
   **Do not confuse the two variables.** `OLD` is the compromised value and must
   die with the session. The *new* value (5(c)'s success condition, step 4's
   `printenv`) is a different variable and a different lifetime. Naming them
   apart matters more than it looks: a session that keeps `OLD` around "just in
   case" has recreated the backup §2 forbids, in the shell.
   (iii) Count online players; a non-zero count stops the plan pending the
   lead's word.
2. **Rotate the Secret.** Generate, validate length 48 (section 2), `kubectl create secret
   ... --dry-run=client -o yaml | kubectl apply -f -`. Value never printed.
3. **Restart the server** so the env re-reads and `server.properties` is
   rewritten: `kubectl rollout restart deploy/minecraft-test-server`.
4. **Change nothing on disk. Verify the restart regenerated holders 3 and 4.**
   These two files are **not independent holders**: they are *derived*. The
   image writes them on every start, at `/image/scripts/start-configuration:87-88`,
   from `$RCON_PASSWORD`, and only removes them when rcon is disabled entirely.
   Measured: pod start `11:57:37Z`, both files `11:57:58Z` (15 ms apart from each
   other -- one script writing both in sequence). So step 3's restart rewrites
   them from the new env automatically, and editing them by hand would only be
   overwritten on the next start.
   - After the restart, confirm both files' mtime is **newer than the restart**,
     and that each fingerprints to the new value.
   - If either still holds the **old** value, STOP and report. That means the
     start script did not run, or `RCON_PASSWORD` is not what was written to the
     Secret -- not that the file needs editing.

   **Correction of an earlier version of this step, and of the sentence that
   preceded it.** The first correction called these "operator convenience files
   nobody declared" and offered deleting them. Both claims were inferences from
   the fact that the table did not list them, not measurements: the mtimes and
   the generating lines above are the evidence, and they say the opposite. An
   undeclared-looking file is not an unowned one; check who writes it before
   deciding who should stop writing it.

5. **Verify.** (a) rcon with the new password → a real command returns a reply;
   (b) the old password is refused; (c) **all four** holders fingerprint to the
   new value, and a full rescan returns **zero** hits for anything that is not
   the new value; (d) the deployment is Ready and the server accepts players.
   (c) is the step that would have caught the missed holders, and it is a
   *scan*, not a list of known paths — checking the four paths only proves the
   four paths were changed. The mtime check in step 4 and this scan are not
   redundant: the mtime says the generator ran, the scan says no copy anywhere
   still carries the old value.
   **(c) runs in the same session as step 1 and searches for `$OLD`.** The scan
   key is the variable step 1(ii) captured, fed to the in-pod grep on stdin —
   the exact shape proven in §1, including its positive control, which is
   repeated here: run the same command with the string `rcon.password=` first
   and confirm it reports a hit. A scanner that cannot find a string it is
   known to contain will report a clean zero, and two of my attempts did.
   After (c) returns zero, clear the variable and close the session: that is
   what makes "no backup was kept" true rather than intended.
   **(c) also runs under step 1(ii)'s tracing guard**, for the same reason: the
   grep is fed the value on stdin, but a traced *re-expansion* of `$OLD` into
   that pipeline is a traced line too. Turning tracing off at the assignment and
   back on before the use would leak at the use. The guard brackets both.
   **A stronger (c), found by executing this (2026-11-11, rotation run).** The
   form above searches for the old value, so it needs `$OLD` to survive from
   step 1 to step 5. In the real run it did not: step 1 ran before a context
   compaction and step 2 after, so the variable was gone and (c) could not run
   as written. The scan that *did* run needs no old value at all — it
   **enumerates every rcon password assignment on the volume and inspects what
   each carries**, requiring each to hold the new value. This is strictly better
   than the prescribed check, because the prescribed one assumes the set of
   holders and searches inside it, while this one enumerates the set. §1's
   original scan failed in exactly that way: it chose its files by extension and
   missed two dotfiles. Prefer the enumerate form.

   **The scan is published: `evidence/rcon-enumerate-scan.sh` (`344f7f2`).**
   What it established: the new value is 48 hex characters; **three rcon
   assignments** exist on the volume — `server.properties`, `.rcon-cli.env` and
   `.rcon-cli.yaml` — and all three carry the new value, compared as a **set**
   (`comm -23`), not by count; two further `password=` fields belong to other
   software (`ae2webintegration.toml` and the bundled Showdown server's JS),
   are **named rather than silently dropped**, and are known not to carry the
   rcon value. RC=0.

   **A hole a reviewer found in that scan is closed, and the closure is a test.**
   A bare `password=` holding a *stale* value used to be classified `OTHER`,
   printed, and never checked — so the final "every rcon assignment carries the
   new value" passed with an unlisted holder present. That is the enumerate
   form narrowed back into the search-inside-a-known-set form, i.e. the exact
   failure it exists to prevent. Now any `password=` that is neither the new
   value nor one of the two known non-rcon *paths* is `UNKNOWN`, and `UNKNOWN`
   fails the run. The allowlist is by path, not by value digest: a digest
   allowlist would commit the AE2 credential's fingerprint here, which is the
   oracle mistake this rotation keeps unmaking.
   `evidence/rcon-scan-selftest.sh` extracts the real decision function from
   the scan (not a copy — a copy agrees with itself) and drives it with five
   fixture outputs. The stale-holder case fails the gate; the three-holder case
   passes. Its first version **proved the hole was still open**: `UNKNOWN` was
   printed and the exit status was 0, because the gate lived in a code path the
   fixture never reached. A fix to classification is worth nothing until the
   decision reaches it.

   **No fingerprint is published here.** A 16-hex digest of a live credential
   is a cheap way to check a guess — §1 says so at `:28`, and it applies to the
   *new* value exactly as it did to the old one. The numbers appear in the run
   log, which is where a credential's fingerprints belong; this document says
   what the scan established.
   It took **four broken versions** to become a check that can fail, and each
   broke the same way — a control that passes on garbage: wrong pod selector
   (the agent, which has no `/data`); the value piped on stdin to `sh -s`,
   which executes stdin as commands, leaving the needle empty so an empty grep
   matched 20+ files **and the control passed** (20 > 3); the script written to
   the wrong host's `/tmp`; and classifying assignments by whether the file
   says "rcon", which put both real dotfiles in `OTHER` so the final "every
   rcon assignment carries the new value" went green with two of the three
   holders outside the checked set. The `len(NEW)==48` gate is the only check
   that caught the empty-needle case; a hit-count control cannot.
   `$OLD`-based (b) was left **unmeasured** in that run for the same reason and
   is recorded as such rather than passed. The lead's ruling (15:31Z): do not
   re-run it — recovering the old value would mean pulling it back out of a
   transcript, which is the copy §2 forbids. It is implied by the enumerate
   scan's zero.
6. **Report** fingerprints and lengths only.

---

## 4. Rollback

There is no value rollback by design (§2). If step 5 fails:

- If the **server will not start** with the new value, the fault is in the
  write, not the value: re-apply the Secret from the same generated value,
  restart, and re-verify. Rolling back to the old password is not an option.
- If **the old password still works, or §5(c)'s scan still finds it**, the
  rotation did not take: a holder was missed. Re-run §1's value scan before
  retrying, because a surviving old value means a holder outside this table.
  This is not hypothetical — the first version of §1 missed two holders, and the
  scan, not the table, is what found them.

---

## 5. Out of scope

- Prod. Different value, untouched.
- Dropping the NodePort — listed in §1, decided by the lead after this lands.
