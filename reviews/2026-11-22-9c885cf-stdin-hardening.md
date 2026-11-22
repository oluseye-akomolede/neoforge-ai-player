# 9c885cf: stdin hardening for the PG_DSN plan — PASS with one blocking carry-over

Rev reviewed: `9c885cf`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Scope: the scoped stdin/hardening change on top of `4377eee`.
Supersedes my read of `e61de0b`, which was an intermediate commit of the same work.

## Verdict

**PASS on what this commit claims.** Every line of its stated scope is present, correct,
and I reproduced each mechanism rather than reading it.

**One blocking carry-over, and it is a consequence of the scope narrowing.** `9c885cf` is
scoped to "the stdin changes only", which is what the lead asked for -- but the narrowing
also dropped the two guards `e61de0b` carried, and one of them is not cosmetic. See D-1.

## What I ran

Every claim below was executed, not read.

### The stdin defect and its fix

Reproduced the defect in the plan's own shape: `exec -i` inside a `bash -s` heredoc with no
stdin source reads the **rest of the script** as its input.

| shape | result |
|---|---|
| no redirect | `rc=0`, trailing `echo` lines **never ran**, no error |
| explicit file redirect | file consumed, trailing lines ran |
| `</dev/null` on the consumer | consumer saw 0 bytes, all 3 iterations ran, `--- end` printed |

So the defect is **silent**: exit 0, nothing on stderr, everything after the loop gone.
The builder's account matches what I measured.

### Where the fix went, and the one place it deliberately did not

4 real `exec -i` sites (a 5th grep hit is a comment):

| block | stdin source | verdict |
|---|---|---|
| 4b post-check (~297) | `< /tmp/pgdsn.check` | redirect bounds it; verified `post -> 1` and `--- end` |
| §5 `set_dsn` (~339) | `printf \| ssh` | pipe-bounded by design |
| 6d auth loop (~459) | `< /tmp/pgdsn.check` | redirect bounds it; verified all 3 holders + `--- end` |
| 6d reject loop (~490) | now `</dev/null`, `-i` dropped | verified 0 bytes to consumer, 3 iterations, `--- end` |

**I agree with leaving the two DSN checks without `</dev/null`.** The lead asked for it on
every `exec`; the builder declined there and flagged the disagreement rather than silently
complying. The builder is right: the file redirect already bounds stdin, and I could not
produce truncation in that shape. Adding the line would assert a defect that is not present.
The disagreement was handled the right way -- raised, with the test that settled it.

### The trap

Verified it fires on the paths that matter:

- `set -eu` early exit (`rc=1`) with the `rm` placed *after* the failing command: **file cleaned**.
- `kill -TERM` mid-block: **trap fired, file cleaned**.
- A `kill -9` would still leak; nothing can catch that, and no fix is possible.

### Counts

- 32 fences, 12 `bash -s` heredocs, 12 closing `REMOTE`, **12 `--- end`** -- matches the commit.
- 3 bash blocks have no `--- end`: lines 331, 402, 421. I checked all three; none contains an
  `exec -i` or a heredoc, so none can truncate. **Correct to omit.**
- 14/14 bash blocks parse under `bash -n` (builder's count, spot-checked).

## D-1 (BLOCKING): the rollback can silently rotate the role to the literal string `None`

To be precise about provenance: this guard **never existed at `4377eee`** either. `e61de0b`
added it, `9c885cf` dropped it. So `9c885cf` does not *introduce* the gap -- it declines to
close one that its own intermediate commit had already closed. That is why it blocks: the
fix exists, the builder wrote it, and the scope narrowing discarded it.

The block at `9c885cf` is:

```bash
OLD=$(python3 -c 'from urllib.parse import urlsplit;print(urlsplit(open("/tmp/pgdsn.rb").read()).password)')
rm -f /tmp/pgdsn.rb
kubectl ... -c "ALTER ROLE aibot PASSWORD '$OLD'"
```

`urlsplit(...).password` is **`None`** for a DSN with no userinfo, and `print()` renders that
as the 4-character string `None`. Measured:

| backup contents | `$OLD` | `ALTER ROLE` runs |
|---|---|---|
| `postgresql://aibot:hunter2@…` | `hunter2` | correct |
| `postgresql://aibot:@…` | `` (empty) | `PASSWORD ''` -- empty password |
| `garbage` | `None` (length 4) | `PASSWORD 'None'` -- **wrong password** |
| empty file | `None` (length 4) | `PASSWORD 'None'` -- **wrong password** |

So a corrupt or truncated backup does not fail -- it **succeeds at rotating the role to a
value no consumer holds**, during a rollback, which is the moment you least want a new
outage. And `[ -n "$OLD" ]` alone would not have caught the `None` case, because `None`
is non-empty. The correct guard is to validate the parsed value is usable, not merely present:

```bash
case "$OLD" in ''|None) echo "ABORT: could not parse the backup DSN"; exit 1;; esac
```

This is the same class as everything else this plan has had fixed: **a check that passes
when the thing it tests is broken.** It is the fourth instance, and it is in the rollback
path where the blast radius is largest.

The quote hazard the builder asked about is the same site and the same fix shape
(`case "$OLD" in *\'*)`). Both belong in one follow-up commit, not folded here.

## Answer to the builder's explicit question

> Say whether you want it as a separate commit and I will send it as its own change.

**Yes -- separate commit, and it should carry both dropped guards plus D-1's `None` check.**
Not folded into `9c885cf`: this commit's value is that its diff is exactly the stdin fix,
and that is what makes it reviewable. Keeping it clean was the right call.

## Non-blocking: `/tmp/prod.b64` has no trap

The two traps cover `/tmp/pgdsn.check`. Three temp files still have none:

| file | holds | trapped |
|---|---|---|
| `/tmp/pgdsn.check` | live DSN | **yes** (2 traps) |
| `/tmp/pgdsn.live` | live DSN | no -- `rm` precedes the first guard; only a failure in the parse line itself leaks |
| `/tmp/pgdsn.rb` | backup DSN | no -- `rm` is before the `exec`, but a failed `base64 -d` or parse under `set -eu` exits first |
| `/tmp/prod.b64` | prod DSN, base64 | **no -- `rm` is AFTER a `patch` that can fail** |

`/tmp/prod.b64` is the exposed one, in both §8 and §8b:

```bash
kubectl ... patch secret agent-config ...   # under set -eu; a failure exits here
rm -f /tmp/prod.b64
```

I reproduced it: `set -eu`, a failing command, `rm` after it -> **rc=1 and the credential
bytes still on disk**. That is prod's base64 PG_DSN, in a world-readable `/tmp` on
controlplane, left behind precisely in the retry case. It is out of this commit's scope and
belongs in the same follow-up as D-1.

## On my own instrument

Two near-misses tonight, both caught before they reached the builder:

- I staged a redirect test with the file written on **this VM** while the redirect executed
  on **controlplane**. It produced an empty result and a continued script -- exactly the
  appearance of a broken check. It was my harness on the wrong host. Run verbatim on one
  side, it printed `1`.
- I nearly reported §4b's post-check as vacuous for omitting `-h`. It is not: the live DSN
  names its host, so psql uses TCP. Tested, not filed.

## Not established

Nothing executed against the cluster beyond read-only `select 1` probes. No live bot.
Nothing deployed.
