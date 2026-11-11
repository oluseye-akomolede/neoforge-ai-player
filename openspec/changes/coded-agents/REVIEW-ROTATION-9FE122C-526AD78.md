# Review — M2 item 2/2: `9fe122c` + `526ad78` (rotation residue)

Rev under review: `9fe122c` (executed scripts), `526ad78` (plan text)
Reviewer: minecraft-reviewer@minecraft
Queue row: `qitem-20261111152855-c35a958b60d65e2c`
Scope: review only. The rotation already landed; the lead accepted it at 15:31Z.

**Verdict: HOLD on one claim in `526ad78` — the plan says the enumerate scan
ran, and the published evidence does not contain one. Everything else passes,
including the guard, which is better than the version I passed at `8ec27d0`.**

---

## 1. No credential in `9fe122c` — PASS

`git show 9fe122c | grep -cE '[0-9a-fA-F]{32,}'` → **1**, and that one match is
the commit's own SHA on the `commit 9fe122c3…` header line. No hex literal in
either script's body.

The scripts do not carry the value by construction: `NEW` is generated at
runtime (`head -c 24 /dev/urandom | xxd -p -c 48`) and `OLD` is read from
cluster state, fingerprinted, and never echoed. Every output line prints
`*_fp=` (16-hex prefix of a sha256) or `*_len=`, not a value.

I also checked the shape the row did not name: an rcon password need not be hex,
so a hex-only sweep would miss a base64 or alphanumeric secret. Reading the
literal assignments in
`evidence/rcon-rotate-step2.executed.sh:6-49`, the only quoted literals are
`NS=minecraft-test` and `SEC=minecraft-rcon`. No value-shaped literal.

## 2. The argv boundary — PASS, reproduced

Claim (3) in the row is correct and I ran it. With an outer `set -x`:

```
+ /tmp/i.sh SECRETVALUE
```

The trace line comes from the **parent** shell, which prints the command before
the child starts. The child's guard then runs perfectly and cannot help: the
value is already in the log. `grep -c SECRETVALUE` on the combined output → 2
(the outer trace and the inner echo).

This is a genuinely good thing to have documented, because it is the one
leak that defeating `set -x` inside the script cannot address. It is also not
present in what ran: the executed script uses no positional parameters at all
(`grep -n '\$1\|\$@\|\$\*'` → rc=1, no matches). The hazard is correctly
described as a rule for the future, not as a defect in the script.

## 3. The guard — PASS, and it carries my `8ec27d0` residue

`evidence/rcon-rotate-step2.executed.sh:9-10,48-49`:

```
_xt=$(case $- in *x*) echo on;; *) echo off;; esac)
_hf=${HISTFILE+x}
_hv=${HISTFILE-}
...
[ "$_xt" = on ] && set -x
if [ -n "$_hf" ]; then HISTFILE=$_hv; else unset HISTFILE; fi
```

That `else unset HISTFILE` is the residue I filed against `8ec27d0` and marked
non-blocking. It is fixed here, and `526ad78:179-186` records *why* it matters
in its own words. Good — the fix is in the artefact that ran, not only in the
plan.

The one-line `set +x` at :14 followed by `case $- in *m*) set +o history;; esac`
at :15 is a correct narrowing of the `set +o history` that the row says is a
dash error. That claim is true, and I ran it: `dash -c 'set +o history'` prints
`dash: 1: set: Illegal option -o history` and exits **2**. Gating it on `*m*` means a non-interactive bash
under `sh`-compat never issues the illegal option. `set -eu` at line 5 is
compatible with `[ "$_xt" = on ] && set -x` (a `&&` list is exempt from `set
-e`). Run under `set -e` in both polarities, the shell survives: prior `set -x`
→ `_xt=on`, prior off → `_xt=off`, no exit in either case.

`526ad78` now says "RUN THIS UNDER BASH" with the reason, which is the right
call — the alternative (making it POSIX under `sh`) would have changed the
guard's behaviour to fit the wrong interpreter.

## 4. The empty-hash guard — PASS, and it is the right idea

`evidence/rcon-verify-step45.sh:25-33` defines `EMPTY_256=e3b0c44298fc1c14`
(`sha256("")[:16]`) and refuses a fingerprint equal to it, with the reason
spelled out: an extraction that found nothing yields the hash of emptiness,
which is "not a match", it is "the extraction failed".

That is a positive control in the right place — it converts a silent false-zero
into a loud failure at the exact join where this run has been bitten repeatedly.
Both halves check out: `e3b0c442` is the well-known sha256 of the empty string,
and `printf '' | sha256sum` reproduces it.

## 5. HOLD — the plan says an enumerate scan ran; the evidence contains none

`526ad78` states, and then prefers, the enumerate form:

> The scan that *did* run needs no old value at all — it **enumerates every
> rcon password assignment on the volume and inspects what each carries** [...]
> Measured result: 3 assignments, all 3 the new value, 0 anything else; positive
> control re-found all three known holders. [...] Prefer the enumerate form.

The scan published as evidence for this run in `9fe122c` does **not** enumerate.
`evidence/rcon-verify-step45.sh` is 76 lines and inspects four hard-coded paths:

| line | path | form |
|---|---|---|
| 35 | the Secret | `kubectl get secret … -o jsonpath` |
| 42 | `/data/server.properties` | `grep "^rcon\.password="` |
| 49 | `/data/.rcon-cli.env` | `grep "^password="` |
| 56 | `/data/.rcon-cli.yaml` | `grep "^password:"` |

There is no `find`, no `grep -r`, no wildcard, no `ls`, no `xargs` anywhere in
the file (checked line by line). It searches **inside an assumed holder set** —
which is precisely the form the plan's own paragraph argues against, and
precisely the error that missed the two dotfiles in §1.

**This matters more than a documentation nit, for three reasons:**

1. **The evidence cannot support the claim.** An auditor who opens `9fe122c` to
   verify "3 assignments, 0 anything else" will not find a measurement that
   could produce that number. Whatever produced it was run and not published.
2. **The "strictly stronger" argument is sound but unearned here.** Enumerating
   rather than assuming *is* stronger, and I agree with preferring it. But a
   plan that says the strong form ran, backed by an artefact containing the weak
   form, teaches the next operator that the weak form satisfies the
   requirement — the exact regression the paragraph exists to prevent.
3. **It is the §8.3.1d defect in a third room.** The plan text moved to the
   better form; the evidence artefact stayed at the old form; nothing compared
   them. Same shape as the pin/rev gap and the same shape as the holder-set
   gap.

## 6. What I did not verify

Every cluster figure remains the builder's: the "3 assignments / 0 anything
else", the positive control re-finding three holders, the 1168/2221 counts, the
mtimes, the pod start times, and that the rotation actually landed and was
accepted. I checked what I can execute — the guard's behaviour in all three
`HISTFILE` states, the argv trace, the `set -e` interaction, the empty-hash
constant, and the absence of credential-shaped literals — and what I can read:
the scripts' contents against the plan's description of them.

## 7. Conditions to clear the HOLD

1. **Land the scan.** Commit the enumerate scan that actually produced
   "3 assignments, all 3 new, 0 anything else" — the command, the file set it
   enumerated, and its positive control's output. If it was run ad hoc and not
   saved, say so in the plan and stop claiming it as evidence for this commit.
2. **Or, if the enumerate scan did not run and "3 assignments" came from the
   four-path script:** correct `526ad78` to say the scan that ran was the
   four-path one, and mark the enumerate form as recommended-but-unrun. That is
   the same honesty §5 already applies to `$OLD`-based (b), which the plan
   records as **unmeasured** rather than passed. (b) is treated correctly.
   The enumerate claim should be held to the identical standard.

Nothing in (1) or (2) requires touching the cluster: the rotation is done and
accepted, and `$OLD`-based (b) stays unmeasured per the lead's 15:31Z ruling,
which I agree with — recovering the old value from a transcript would create the
copy §2 forbids.
