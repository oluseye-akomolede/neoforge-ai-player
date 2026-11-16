# Review — agent-script-runner, 9782ce4..5df8dcc

Range under review: `fa9c1e8`, `7ca19e8`, `3a3f197`, `e50fdf1`, `145f5ef`,
`eae7861`, `5df8dcc`
Head at review time: `5df8dcc` (the request named `eae7861`; `5df8dcc` landed
after it and is included below because the request says "against the current
head" and it changes the build path)
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS**

Repo: `/home/sigmastrain/minecraft/agent-script-runner` (local, no remote; this
is not the neoforge tree — the runner's code lives here, and reviewing the
neoforge HEAD would have reviewed the wrong repository).

`npm test` via the committed script (`node --test --test-timeout=40000
"test/*.test.mjs"`) at `eae7861`: **63 tests, 63 pass, 0 fail, npm exit code 0**
— captured from npm itself, not from a pipe.

## Does the guard now do the job? (fa9c1e8)

**Yes.** Two changes, both addressing findings I raised at `9782ce4`.

### Eviction reaches the target in one pass

My finding was arithmetic: the budget-to-limit gap is ~1 GiB and the per-bot
cap is 128 MiB, so **8 bots fill the gap inside one 1 s interval** while the old
guard reclaimed one victim per second — it could not outrun the thing it exists
to stop. `enforceBudget` now loops until under budget, and the code comment
carries the calculation rather than a restatement.

Two things the loop does that a naive loop would get wrong, both present:

- **it will not empty the fleet.** `live.length <= 1` stops the loop and returns
  `stillOverBudget` rather than satisfying the budget by killing everything. An
  unsatisfiable budget is reported, not hidden.
- **the floor sits after the under-budget check.** `chooseVictim` returns
  `victim: null` when total is at or under budget, and only then does the
  `live.length <= 1` branch apply. So a lone survivor that is *under* budget
  returns quietly and does not raise a spurious `stillOverBudget`. Ordering
  matters here and it is right.

No infinite loop is possible: total is the sum of the children's RSS, so if
every child reads 0 the total is 0 and the loop exits on the under-budget path.

### Re-entrancy is guarded

The flag is set before the first `await` and cleared in `finally`. The reason is
in the comment and it is the correct one: `stop()` awaits the child's `exit`
event after `SIGKILL`, and a child in uninterruptible sleep cannot be hurried.

### The timing the builder flagged as unmeasured — now measured

The handoff said 8 sequential stops inside one interval was unmeasured and
"would rather say so than imply it." I measured it rather than accept the hedge:

**8 sequential `stop()` calls: 42.8 ms total, 5.3 ms each — 4.3% of the 1 s
interval.** Stops would need to be ~23x slower to reach the interval at all, and
past that the re-entrancy flag degrades the guard to one pass per pass rather
than stacking passes. The one unbounded case is a child in D-state, which
`SIGKILL` genuinely cannot hurry; that is bounded behaviourally (no stacking) and
not numerically, which is as far as it can honestly be bounded.

### Controls run in both directions

The builder reported that reverting `9782ce4`'s `fleet.js` under the new tests
fails 3. I re-ran it myself rather than reading the claim: **3 fail — the
evict-to-target test, the re-entrancy test, and the pre-existing
largest-victim test whose return shape the loop changed** — and 37/37 restored
afterwards. The failing set is the right set, so the tests are controls and not
decoration.

## HTTP surface, runner wiring, image (3a3f197, e50fdf1, 145f5ef)

### Auth on 8080 — the strongest part of this range

- **Per-game tokens from the environment** (`RUNNER_TOKEN_<GAME>`), one per game,
  with a startup failure if none are configured or one is too short. That is the
  right failure direction: a missing token fails the boot rather than refusing
  every call with no obvious cause.
- **Auth is checked before the body is read.** A 401 is returned without parsing
  the request, so an unauthenticated caller cannot make the runner allocate.
  Stated in the code as the reason.
- **The presented token is compared against every configured token**, not looked
  up in a map, because a map miss returns early and leaks prefix length by
  timing. Two games, two compares.
- **`tokenMatches` is length-constant.** `timingSafeEqual` throws on length
  mismatch, so a mismatch still spends a compare against an equal-length dummy.
  This is the detail most implementations miss.
- **The `game_id` in the body must match the token that authenticated the call**,
  so a cardgame token cannot act on minecraft's sandboxes.
- **Every path on 8080 goes through the same handler**, and auth precedes the
  route switch — there is no route that bypasses it. Three endpoints
  (`/v1/tick`, `/v1/load`, `/v1/destroy`), matching §1.

Token values never appear in the code, a log line, or an error; only the game
name does.

### `/readyz` on 8081 leaks nothing

`/readyz` returns `{ready: boolean}` and `/healthz` returns `{ok: true}`.
Nothing else — no bot counts, no game names, no version, no memory figures. The
response sets only `content-type` and `content-length`. Non-`GET` on the probe
port gets 405, unknown paths 404.

The two-listener choice is justified in the code and the justification is sound:
a probe is worth having exactly when the contract port is saturated, and a shared
listener would fail the probe for the same reason it failed the work.

Note (not a finding): the probe port is **unauthenticated by design** and binds
`0.0.0.0`. With the §10 NetworkPolicy that is reachable only from the two named
peers; without it, it is reachable by anything that can route to the pod. The
policy is now load-bearing for the probe surface, not only for the contract
surface — worth knowing when the policy is edited.

### The image is built from a committed tree (5df8dcc)

`5df8dcc` closes the stale-label failure the builder found. Mechanism, read from
the file:

- `ARG GIT_COMMIT` has **no default**, and a `RUN test -n "${GIT_COMMIT}"` fails
  the build with a message. `"unknown"` is a legal label value, so a
  provenance-less image is indistinguishable from a good one at run time; the
  build is the only cheap place to catch it.
- `scripts/build-image.sh` moves the invocation into the repo, reads the sha from
  git, **refuses a dirty tree** (a label names a commit, so the bytes must be
  that commit's), uses this rig's `DOCKER_CONFIG`, and prints tag, revision and
  image id together.

The dirty-tree refusal is correct and is currently active: **this working tree
has an untracked `src/binding.js`**, so no image can be built from it until that
file is committed or removed. That is the guard working.

I did not rebuild the image. That is heavy work, the builder watched both
directions fail and pass, and the mechanism is readable in the file. **A digest
and a tick transcript are still owed before any image is quoted as verified** —
neither is in this range, and a digest without a tick through it is the claim
that aged badly once already.

## Unit labels (7ca19e8)

`8.01 GiB` and `113.9 MiB` throughout, and the earlier `GB`/`MB` drift is gone
as a live claim. Four `MB` occurrences survive and all four are the record, not a
live size: `:183` and `:224` quote the old wrong arithmetic, `:187` is a measured
RSS figure where MB is the observed number, `:193` is the sentence defining the
units. "No bare GB" is true; "no bare MB" is false; neither is the claim that
matters — every surviving MB is a quoted measurement or a quoted mistake.

## NetworkPolicy ports (eae7861)

The contract gained a ports bullet at `1a59ca4`; LAYOUT did not, and LAYOUT is
where the YAML is written from — so an implementer reading LAYOUT would have
written a rule with no `ports:`, which is a wildcard, not an unset field. Fixed
at `eae7861`: the ingress sentence now carries "on TCP 8080 and 8081 only", the
paragraph explains why omission widens rather than narrows, and it states
explicitly that the reasoning is repeated here because LAYOUT is the file the
YAML comes from and the two must not diverge.

## Findings

**None blocking.**

1. **`src/binding.js` is untracked** (214 lines, step 3). It is outside this
   range. Flagging it because (a) it is the step the run plan is blocked on, and
   (b) it makes the tree dirty, which the new build script correctly refuses.
   Not reviewed here.

2. **`GIT_TAG` has no equivalent guard to `GIT_COMMIT`.** A tagged build with an
   empty tag labels the image `version=""`. Smaller hole than `revision`, same
   shape, one line to close.

3. **The probe port is now dependent on the NetworkPolicy.** See above — noted so
   that editing the policy is understood to affect the probe surface too.

## Method

- Runner code reviewed in the runner repo; the neoforge tree carries the tasks
  and the contract, not this code. The head reviewed is `5df8dcc`, not the
  `eae7861` named in the request, because `5df8dcc` is current and changes the
  build path.
- `npm test` run via the committed script with npm's own exit code captured.
- The guard's revert control re-run rather than read.
- The unmeasured timing measured (42.8 ms / 8 stops).
- Every "does not leak" claim checked against the handler body, not the comment.
