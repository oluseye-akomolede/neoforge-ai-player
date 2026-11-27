# Review: O-1 — a failed search reports the failure (`6c5c9fe`)

**Verdict: PASS at `6c5c9fe`, with one finding (F-1) that is not a defect but a
coverage gap the builder disclosed and I confirmed by mutating it myself: the
handler wiring — the half that makes the change work end to end — is not
witnessed by any test in the repo. It is correct; I checked it by eye and by
reading the concurrency, and it must be checked again by the live probe (5.6).

- Repo: `neoforge-ai-player`, branch `spec-find-blocks-failure`
- Reviewed rev: `6c5c9fe` (parent `a9331a9`, off `938dba1`)
- Rows: `qitem-20261127114454-35c607cc1c5dffb4` (change), `qitem-20261127120444-ba3b3d86f7e8e349` (ruling A)
- Earlier review: `reviews/2026-11-27-a2-o1-companion-9a8a083.md` (the guard), `2026-11-27-a2-query-shape-4cf6a63.md` (O-1 raised)

Every measurement below was taken from a `git archive` extraction of `6c5c9fe`,
not from the builder's worktree, except the JUnit run, which needs the Gradle
cache and was run in the builder's tree and then restored clean.

## What changed

Five files: `HttpApiServer.java` (+33), `FindBlocksFailureTest.java` (new, 149),
`script_tick.py` (+22), `test_script_tick.py` (+63), `tasks.md`.

## The mod half is correct, and I followed the race

`searchAnswer(listKey, values, failure)` returns a `LinkedHashMap` with the list
under its verb key and, when `failure != null`, a non-blank `error` string that
falls back to the exception's simple class name. Null or blank messages are
handled; `values == null` becomes `List.of()`, which is a *shape* change from
`Map.of` (which would have thrown NPE on a null list) and a safe one.

The part worth writing down is the ordering, because no test reaches it:

```java
catch (Exception e) { blockFailure.set(e); blockFuture.complete(List.of()); LOGGER.error(...); }
...
sendJson(exchange, 200, searchAnswer("blocks", boundedJoin(blockFuture), blockFailure.get()));
```

Java evaluates arguments left to right, so `boundedJoin(blockFuture)` blocks
**before** `blockFailure.get()` is read. The catch sets the reference *before*it completes the future. `complete` is what wakes the blocked `boundedJoin`, and
a `set` before a `complete` that another thread observes through `get` is a
happens-before chain. So the failure is always visible. I checked the two ways
this could have been wrong:

- **If the order were reversed** (`complete` then `set`), the reader could see
  the completed future and read a still-null reference — the bug would be a
  silent `{blocks: []}` on a real failure. It is not reversed.
- **On timeout**, `BoundedWait.await` throws `Timeout` out of `boundedJoin`, so
  `blockFailure.get()` is never evaluated and the 503 path is untouched, exactly
  as the commit message claims.

Both are correct. Neither is pinned by a test. That is F-1.

## F-1: the wiring is unwitnessed, and I reproduced the survivor

The builder stated this in the commit message and in tasks.md rather than
implying it, then asked me to check it. I did, by running the mutant they
described.

**Mutant, run by me in the builder's own worktree** (needs the Gradle cache the
extracted tree lacks): replaced both `searchAnswer(...)` calls with the old
`Map.of("blocks"|"entities", boundedJoin(...))`. `compileJava` re-ran
(2 executed, 24 up-to-date — not `FROM-CACHE`), and the result was:

```
BUILD SUCCESSFUL     tests="9" skipped="0" failures="0" errors="0"     rc=0
```

**All nine green.** The entire mod half of this change could be reverted and the
suite would not notice. Nine tests, all calling `searchAnswer` directly, is the
right unit for the helper and tells you nothing about whether either handler
calls it.

This is not a request for the builder to bolt on a handler test — entering the
handler needs a Minecraft server and the 47-call-site `sendJson` seam exists
precisely so routes are testable without one. It is the reason **5.6 is
load-bearing rather than a formality**: the live probe is the only evidence that
the wiring works, and it must be run and recorded before this is called done. I
have left 5.6 unticked for that reason.

## F-2: `LOGGER.error` survival is unwitnessed — same class, lower stakes

Deleting both `LOGGER.error` lines also leaves the suite green; there is no
logging seam in `HttpApiServer` to assert against. I verified the lines are
present in the committed source and unchanged by the diff. Recorded as a
property, not a defect: the risk is a lost audit trail on a search failure, and
the diff is one line per verb.

## The agent half, measured

I probed `_normalise_query_result` at `6c5c9fe` across seven shapes:

| input (`blocks`) | ok | reason | message | error |
|---|---|---|---|---|
| `{[], error:"boom"}` | False | error | **boom** | boom |
| `{[], error:"boom", message:"own"}` | False | error | **own** | boom |
| `{[], error:""}` | True | – | – | "" |
| `{[], error:None}` | True | – | – | None |
| `{[], error:False}` | True | – | – | False |
| `{[], error:"x", reason:"timeout"}` | False | **timeout** | x | x |
| `{[{a:1}], error:"boom"}` | False | error | boom | boom |

The `setdefault` semantics hold: a mod-supplied `message` wins; an empty string
is still a success; a mod-supplied `reason` survives. The stated choice — `error`
and `message` carrying the same text — is visible and deliberate, and both tests
assert the exact key set so removing either reddens them.

**Two mutants, both run by me:**
- Removing `value.setdefault("message", value["error"])` → `FAILED (errors=2)`,
  rc=1, the two named tests (`..._answer_marked_failed_...` on blocks and on
  entities). Each verb's own test, not one test covering both.
- Disabling the `error` guard → `FAILED (failures=2)`, rc=1, the same two tests.

Suite at the rev: **`Ran 73 tests` · `OK` · rc=0** (`python3 -B -m unittest
test_script_tick`, cwd `agent/`, summary read from stderr as tasks 5.2 warns —
the first attempt read stdout and lost the tally in script-log chatter).

## Delta and archive — 5.3, 5.4, 5.5 verified by me

- **5.3** `openspec validate find-blocks-reports-failure --strict` → valid, rc=0.
  As tasks 5.3 says, this does not prove the delta *type*.
- **5.4** At the committed rev: 7 live scenarios carried, 0 missing, 3 new. The
  seven are body-verbatim, in order, and the new normative paragraph sits after
  the last live scenario inside the requirement.
- **5.5** Archive dry-run in an isolated extraction of `6c5c9fe`:
  `+ 2 added, ~ 1 modified, - 0`; then
  `grep -c "A Script Declares The Searches"` = **1**, and
  `openspec validate --specs --strict` = **16 passed, 0 failed**. The change is
  archivable, and archiving does not drop a scenario.

## What I did not do

- Did not run 5.6 (the live probe). It needs a test server and is a deploy-run
  check, not a unit test; it is the outstanding gate, and it is the only one.
- Did not review the `qcode`-authored Java line by line *as a generator
  output*; I read the resulting 33-line diff, which is the thing that ships.
- Did not dispute the builder's account of losing a fix to `git checkout --`
  and re-applying by hand. I verified the committed bytes contain the fix
  (seven-shape probe, two mutants); the story of how they got there is not
  something I can check, and the bytes are what matter.

## Instrument notes

- The extracted tree cannot run Gradle offline (`cacheVersionManifest` needs
  `.gradle/caches/minecraft/versions/1.21.1/metadata.json`). The F-1 JUnit
  mutant was therefore run in the builder's worktree, with the file backed up
  first and restored afterward to a clean `git status`. The Python mutants were
  run in the extracted tree.
- `./gradlew ... | tail` reports tail's rc; the `PIPESTATUS` capture and the
  JUnit XML tally are the real result.

## Verdict

**PASS.** The change does what O-1 asked: a thrown search now answers with an
`error` key on both verbs, a genuine empty result stays a success, and the agent
mirrors the text into `message` so the live `{ok, reason, message}` obligation
holds on the path this change makes reachable. The helper is correct, the
ordering is correct, the agent rule is correct and doubled by two named tests.

Ship it when **5.6 passes on a test server**. Until that runs, the one thing
that makes this a fix rather than a well-tested helper is unverified — not
because it looks wrong, but because nothing in the suite can see it.
