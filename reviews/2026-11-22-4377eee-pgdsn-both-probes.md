# PG_DSN plan: `4377eee` closes the authentication probe too — PASS

Rev reviewed: `4377eee`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Closes the gap my `ef18036` review reported, and goes further than I did.

## Verdict

PASS. The builder found that my §6d finding applied to **both** probes, not the
one I named. I checked only the rejection probe and wrote "6d can now fail"; the
authentication probe still ran `psql "$DSN"` inside the pgvector pod, where a
hostless DSN falls to the Unix socket and matches `local all all trust`. That
probe also could not fail. They fixed both.

## Their premise, confirmed by execution

Read-only in the pgvector pod:

| connection | password | result |
|---|---|---|
| `-U aibot -d botmemory_test` (socket) | deliberately wrong | `1` |
| `postgresql://aibot:<wrong>@/botmemory_test` (hostless → socket) | deliberately wrong | `1` |
| `...@pgvector.minecraft-test.svc.cluster.local:5432/...` | deliberately wrong | `FATAL: password authentication failed` |

So a hostless DSN authenticates as anyone. Correct after my `ef18036` review
would have been: *both* probes were vacuous, and my "can now fail" was true only
of the half I tested. Their diagnosis is more accurate than mine.

## The fix, verified in both directions

Both probes now run in `deploy/aibot-agent-test`:

- **Authentication probe** — reads the live DSN from the secret and connects
  from the consumer pod. Ran verbatim: **`1`**.
- **Rejection probe** — constructs
  `postgresql://aibot:<WRONG>@pgvector.minecraft-test.svc.cluster.local:5432/<db>`
  literally, so its host cannot depend on secret contents. Ran verbatim:
  **`rejected`**.

The property that makes this robust is better than "the DSN names its host": a
hostless DSN **inside the consumer pod fails outright**, because there is no
local Postgres there. Verified —

```
OperationalError: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432"
failed: No such file or directory
```

So the check's correctness no longer rests on the secret's contents at all, which
was the shape of the original bug. That is the right fix, and it is why moving the
probe instead of forcing `-h` was the better call.

## 4b moved too, and for the right reason

The post-rehearsal connect now runs in the consumer pod. My `ef18036` review said
that check was genuine *because the live DSN names its host* — true, but that
makes correctness depend on the DSN's contents rather than on the check, which is
the same shape as the bug being fixed. Removing the dependency is cheap and right.

The `ALTER ROLE` blocks stay inside pgvector, deliberately: superuser, and
loopback trust is correct for an admin operation rather than a credential check.
That distinction is stated in the plan and I agree with it.

The "production password" comment typo is fixed at line 265.

## Minor, non-blocking

§4b's rehearsal interpolates `$OLD` into `PASSWORD '$OLD'`. That is safe for the
forward direction, where the new password is `openssl rand -hex 16` and the plan
pins it to hex, so no quote can appear. The rehearsal reads the *current*
password, whose charset nothing in the plan guarantees. If it ever contained a
single quote the statement would break or write a wrong value — and the
post-check would catch it as a 401 on the consumers, so it fails closed and
detectably. Worth one sentence in the plan rather than a code change.

## What I got wrong, twice, in the same way

- `ef18036`: I found the loopback defect in one probe and generalised the fix
  without checking the sibling probe in the same section.
- Earlier: I read my worktree's `agent.py` and reported its line numbers as line
  numbers at the rev.

Both are the same failure — testing the instance in front of me rather than the
claim I was about to write. The builder's response to the second one was to state
the broken-case expectation next to every check, which is a better artefact than
the review that prompted it.

## Not established

Nothing in the plan has executed as a run. The probes above are read-only
`select 1` calls; they wrote nothing and created no persistent object. The builder
states their probes used the live DSN and discarded the result, and that nothing
was written and no bot touched.

No live bot, no deployment.
