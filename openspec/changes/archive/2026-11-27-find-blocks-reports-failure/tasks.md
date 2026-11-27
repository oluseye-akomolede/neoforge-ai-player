# Tasks: a failed search reports its own failure

Each code task names the test that pins it and the mutant that must redden that
test. A task is done when the mutant is run and observed red, not when the test
passes.

Scope: BOTH search verbs. Lead's decision (11:58Z) and reviewer's concurrence
(11:57Z) put `find_entities` in this change beside `find_blocks`; the two catches
are the same three lines in the same file with the same wire shape.

All `HttpApiServer.java` line numbers below were measured at `origin/main`
`bf560d2` with `sed -n 1105,1150p`:

| construct | line |
|---|---|
| `case "find_blocks"` | :1117 |
| `find_blocks` `try` | :1123 |
| `find_blocks` `catch` (completes `List.of()`, logs `findBlocks error`) | **:1124** |
| `find_blocks` `sendJson` — `Map.of("blocks", boundedJoin(blockFuture))` | **:1126** |
| `case "find_entities"` | :1128 |
| `find_entities` `try` | :1133 |
| `find_entities` `catch` (completes `List.of()`, logs `findEntities error`) | **:1134** |
| `find_entities` `sendJson` — `Map.of("entities", boundedJoin(entityFuture))` | **:1136** |
| `scan_data` `catch` — the `error`-key shape being copied | :1420 |

DO NOT cite `:1125` or `:1135` for the catches. Those are the `});` lines one
past each catch; the lead's O-1 message carries them and they are wrong.

## 1. Mod: both handlers distinguish failure from empty

- [x] 1.1 `HttpApiServer` `find_blocks` (`:1117-1127`): on the `catch` at `:1124`
      complete the future with a sentinel carrying the exception, and answer
      `{blocks: [...], error: "<text>"}`; on success answer `{blocks: [...]}`
      byte-identical to today. Factor the `Throwable → answer map` decision into a
      small static method so it is testable without a Minecraft classpath.
      Done: `searchAnswer(String listKey, List values, Throwable failure)` added
      near `healthBody`; `find_blocks` captures into `AtomicReference`, sends
      `searchAnswer("blocks", boundedJoin(...), blockFailure.get())`.
      *Test:* `src/test/java/com/sigmastrain/aiplayermod/api/FindBlocksFailureTest.java`
      (new) calls that method directly, the way `BoundedWaitTest` tests the bound.
      *Mutant that must red it:* revert to `List.of()` with no `error` key. The
      failure and empty cases then produce the same map and
      `blocksFailureAndEmptyAreDistinguishable` fails.
- [x] 1.2 `HttpApiServer` `find_entities` (`:1128-1137`): the identical change on
      the `catch` at `:1134`, answering `{entities: [...], error: "<text>"}`.
      This is the whole reason `find_entities` is in this change rather than its
      own; it is not optional padding.
      Done: same `searchAnswer("entities", boundedJoin(...), entityFailure.get())`.
      *Test:* the same test class, `entitiesFailureAndEmptyAreDistinguishable`
      and the entity twins, against the same static method with the `entities` key.
      *Mutant that must red it (helper level):* make `searchAnswer` return the same
      map for a `null` and a non-null failure under the `entities` key — the
      `entities` cases redden and the `blocks` cases stay green. Proves each verb
      is covered by its own test, not riding the other.
      *Measured limit (say this, do not imply coverage):* reverting the entity
      handler's `sendJson(...)` call to `Map.of("entities", ...)` leaves the whole
      suite GREEN. These tests call `searchAnswer` directly; they do not enter the
      handler. That wiring is witnessed by the diff read and the 5.6 live probe,
      not by JUnit. The class docstring says so; do not let a green run read as
      end-to-end.
- [x] 1.3 Keep both log lines. `AIPlayerMod.LOGGER.error("findBlocks error", e)`
      at `:1124` and `("findEntities error", e)` at `:1134` MUST remain at error
      level with the throwable. A fix that tells the caller but drops the
      server-side log loses the operator's only view.
      *Test:* none — no logging seam exists that a unit test can assert.
      *Mutant:* delete the `LOGGER.error` call while keeping the `error` key.
      **Measured: the mutant leaves the suite GREEN — NOT caught.** No seam
      asserts the log, so the log's survival rests on the diff read, not on a
      test. Said here rather than implied. Both log lines are present (`grep -c`
      = 2) and untouched by the fix.
- [x] 1.4 Success paths unchanged for both verbs. Not its own edit; it is the
      constraint on 1.1 and 1.2.
      *Test:* `blocksSuccessPathIsUnchanged` asserts `{blocks: [<two blocks>]}` and
      `entitiesSuccessPathIsUnchanged` asserts `{entities: [<two entities>]}` carry
      exactly their list key and nothing new. Both green.
      *Mutant that must red it:* add an `error` key to the success map. The test
      must redden; a test that would tolerate an extra key is not pinning the
      promise.

## 2. Agent: one rule for both verbs, pinned at the seam

The agent code is already live (`agent/script_tick.py:_normalise_query_result`,
present at `origin/main` and at `2f019c0`, guard at `:660`). Nothing here changes
it; these tasks prove it reads the mod's new answer. **One scenario covers both
verbs** (reviewer: do not write two) because the normaliser reads the `error` key
without knowing which verb produced it.

- [x] 2.1 `agent/test_script_tick.py`: drive the mod's real failure answers
      `{blocks: [], error: "findBlocks error: ..."}` and
      `{entities: [], error: "findEntities error: ..."}` through
      `_normalise_query_result` and assert (for each) `ok is False`,
      `reason == "error"`, `message` carries the mod's text, `matches == []`.
      `message` carries it only because of the `setdefault("message",
      value["error"])` line added beside the guard (reviewer ruling A, 12:05Z):
      the mod sends the text under `error`, and that line mirrors it so the live
      `{ok, reason, message}` obligation holds on the path this change makes
      reachable. `error` STAYS too — two names for one string, a stated choice,
      asserted by the exact-key-set check in the test.
      Add the twins: `{blocks: []}` and `{entities: []}` with no error key stay
      `ok is True, matches == []`.
      *Mutant that must red it:* delete the guard at `agent/script_tick.py:660`
      (`if value.get("error") not in (None, "", False):`). Both failure cases then
      report `ok=True`. **Measured: 2 red, both `…marked_failed_is_not_reported_as_a_success`
      tests (one per verb)**, 71 still green, ran from `agent/` as
      `(ulimit -v 4194304; nice -n 19 python3 -B -m unittest test_script_tick)`,
      `Ran 73`, `FAILED (errors=2)`. At `9a8a083` it reddened 1 (block only); the
      count is 2 now because the entity twin is new.
      *Second mutant that must red it:* delete the `setdefault("message", …)`
      line. **Measured: exactly those same 2 tests, nothing else** — `Ran 73`,
      `FAILED (errors=2)`, rc=1; restored and re-ran to `Ran 73`, `OK`, rc=0.
- [x] 2.2 `agent/test_script_tick.py`: run declared `blocks` and `entities`
      queries through `run_declared_queries` with the api returning the mod's
      failure maps, asserting each installed `look.queries.<name>` is
      `{ok: false, reason: "error"}` and its siblings are untouched.
      **VERIFIED BY THE REVIEWER (2026-11-27) against `38f3ef0` in a clean
      extraction, by driving the shape directly rather than by naming a test.**
      Both verbs with `{<key>: [], error: "..."}` through `run_declared_queries`
      gave `ok=False, reason='error', message=<the mod text>, matches=[]`; keys
      `['error','kind','matches','message','ok','reason']`. A mixed run with one
      failing and two succeeding queries showed the siblings unaffected
      (`okq` `ok=True` with 1 match, `ent` `ok=True` with 0). Note for the record:
      the three existing `run_declared_queries` tests cover the success path and
      the missing-list path, NOT the error-key path — this requirement is
      witnessed by the probe above, and a future reader should not assume a
      named test covers it.
      **A test whose fake `find_blocks`/`find_entities` raises does NOT satisfy
      this** — it proves the transport's `except` branch, not the error-key path,
      and the guard could be deleted with the suite still green.

## 3. Comment hygiene, in the commit that lands the mod fix

- [x] 3.1 `agent/script_tick.py:628-635` narrates the swallow as
      `HttpApiServer:1123-1126` and speaks of `find_blocks` alone. At `bf560d2`
      the catch is `:1124` and the send is `:1126`; `:1123` is the `try`. Both
      the range and the singular verb go stale with this change, and the
      "Until then…" clause stops being true once an error key ships.
      Done: rewritten to cite catch `:1124` / send `:1126` and `find_entities`
      catch `:1134` / send `:1136`, naming both verbs and the shared rule.
      *Test:* `python3 -m py_compile agent/script_tick.py` and the suite (green).
- [x] 3.2 The `api-http` delta's `HttpApiServer:1117-1127` cite (`:16`) is correct
      at `bf560d2` and stays correct. Do not edit it. Left untouched.

## 4. api-http delta: answered — option B (lead, 12:00Z)

The `api-http` ADDED requirement (`A Failed Block Search Answers With An Error,
Not A Bare Empty List`) and its five scenarios name `/find_blocks` only. With
`find_entities` in scope, the `:1134-1136` change would ship with no api-http
requirement stating what its answer must be. Row
`qitem-20261127115907-7364ff65543d072d` asks reviewer and lead to pick A, B or C.
- [x] 4.1 Resolve A/B/C. Do not start 4.2 before it is answered.
      **Answered: B** (lead, 12:00Z) — a second ADDED `api-http` requirement for
      `find_entities`, block scenarios left byte-identical.
- [x] 4.2 Add the entity requirement/scenarios. Done as a second ADDED
      requirement in `specs/api-http/spec.md`, `A Failed Entity Search Answers
      With An Error, Not A Bare Empty List`, with four scenarios. The five block
      scenarios above it are untouched. The first 71 lines of the file are
      byte-identical to the version on `main` at `938dba1`.
      *Test:* the same `FindBlocksFailureTest` seam, a second case built from
      `find_entities`'s own catch at `:1134`.
      *Mutant that must red it (helper level):* a `searchAnswer` that answers the
      same map for a failure and a success under the `entities` key reddens the
      entity cases and leaves the block cases green — that is "both verbs are
      proved the same way" at the helper seam.
      *Measured limit:* reverting the handler's entity `sendJson` leaves the suite
      green (see 1.2). The entity half is separately proven at the helper; the
      handler wiring is not JUnit-witnessed for either verb.

## 5. Verification

- [x] 5.1 `./gradlew :test --tests '*FindBlocksFailure*' --rerun --no-build-cache`
      with `-Xmx2g`, `--max-workers=2`, `nice -n 19`. Read the JUnit XML tally;
      `FROM-CACHE` is not a run.
      **Measured: `tests="9" skipped="0" failures="0" errors="0"`, rc=0**, from
      repo root `neoforge-ai-player/`; `searchAnswer` confirmed in the compiled
      `HttpApiServer.class` via `javap`.
- [x] 5.2 From inside `agent/`: `python3 -B -m unittest test_script_tick`. Report
      `Ran N` and `OK` from stderr with the cwd and command. `-B` so a stale
      `.pyc` cannot re-run the unmutated module under a mutant.
      **Measured: `Ran 73 tests`, `OK`, rc=0**, cwd `agent/`, command
      `(ulimit -v 4194304; nice -n 19 python3 -B -m unittest test_script_tick)`,
      redirected to a file and grepped (the suite prints script-log chatter to
      stdout before the stderr summary).
- [x] 5.3 `openspec validate find-blocks-reports-failure --strict` returns rc=0
      "valid" — recorded, but it does NOT prove the delta type. It counts
      ERROR+WARNING; an ADDED-only delta that should be MODIFIED is INFO. The
      type is proven by the scenario check below.
      **Measured: "Change 'find-blocks-reports-failure' is valid".**
- [x] 5.4 Delta type check, run and record the output: the delta must carry all
      7 live scenarios of `bot-coded-agents/spec.md:1619` **verbatim** (bodies,
      not just names) plus the 3 new ones. Measured once already: 7 carried, 0
      missing, 3 new, intro paragraph identical. Re-run it at the committed rev.
      **Re-run at HEAD: live scenarios 7, delta 10, live missing from delta [],
      new in delta 3 — carried 7, new 3.** Body-level verbatim check (earlier)
      confirmed 7 of 7 unchanged, intro identical.
- [x] 5.5 Archive `find-blocks-reports-failure` only after landing and review.
      `script-lookups-and-results` is ALREADY archived on `origin/main`
      (`bf560d2`), so there is no ordering constraint left — the superseded
      task 3a is void. After archiving,
      `grep -c "A Script Declares The Searches" openspec/specs/bot-coded-agents/spec.md`
      MUST be 1.
      **DONE (reviewer, 2026-11-27).** Archived off `origin/main` `38f3ef0` as
      `2026-11-27-find-blocks-reports-failure`. `openspec validate --specs
      --strict`: 16 passed, 0 failed. Archive applied `+2 added, ~1 modified,
      -0 removed`; post-archive scenario counts read back per requirement —
      `A Failed Block Search` 5, `A Failed Entity Search` 4, the modified
      `A Script Declares The Searches` 10 (7 carried in order + 3 new). The four
      archived files are sha256-identical to their `38f3ef0` originals. The
      `script-lookups-and-results` ordering constraint was already satisfied
      (`bf560d2`), so nothing was ever at risk of archiving ahead of it.
- [x] 5.6 End-to-end, on a test server: a search that throws in a live world
      reaches `look.queries.<name>` as `{ok: false, reason: "error"}` for both a
      `blocks` and an `entities` query. This is a deploy-run-plan check, not a
      JUnit test; record the command and its output in the deploy notes.
      **AMENDED BEFORE RUNNING (2026-11-27): the probe cannot reach
      `reason:"error"`.** `findBlocks` (`BotPlayer.java:1286`) and `findEntities`
      (`:1313`) are total — no `throw`, and every call they make is pure or
      total — so no request data makes them fail. Fault injection was rejected
      (a leftover fault jar has a normal `promote` route to prod) and the
      handler-level unit test was rejected (`BotPlayer`'s constructor is private
      `:77`, `player` is `private final` `:55`, so any testable helper is a
      sibling and the `Map.of` revert stays green). The error path is therefore a
      named limitation: a diff read, covered by unit tests on `searchAnswer`
      only. See 5.6a.
- [x] 5.6a Run the clean-jar probe and record what it actually shows. **DONE
      (lead, 2026-11-27, test server on md5 `78572859`, rollback `2fd5ea53`).**
      Axiom declared `blocks 'stone' r32`, `blocks 'zzzznotablock'`,
      `entities 'zzzznotanentity'`. Log line verbatim:
      `O1Q stone[ok=true n=10 hasErrorKey=false] emptyBlocks[ok=true n=0
      hasErrorKey=false] emptyEntities[ok=true n=0 hasErrorKey=false]`.
      Read narrowly: success returns real matches (n=10) with no error key, and
      a genuine empty stays `ok:true` with no error key **for both verbs** — the
      boundary O-1 must not break is proven live. The error path is NOT exercised
      and this result does not show it. **Deploy notes MUST NOT say "probe
      passed".** The correct sentence is: "Success, empty and timeout verified
      live; error path not exercised, covered by unit tests on `searchAnswer`
      only." A run recording exactly success/empty/timeout is the expected
      result, not a failed probe — do not retry it.
