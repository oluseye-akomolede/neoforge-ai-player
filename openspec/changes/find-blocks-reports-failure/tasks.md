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

- [ ] 1.1 `HttpApiServer` `find_blocks` (`:1117-1127`): on the `catch` at `:1124`
      complete the future with a sentinel carrying the exception, and answer
      `{blocks: [...], error: "<text>"}`; on success answer `{blocks: [...]}`
      byte-identical to today. Factor the `Throwable → answer map` decision into a
      small static method so it is testable without a Minecraft classpath.
      *Test:* `src/test/java/com/sigmastrain/aiplayermod/api/FindBlocksFailureTest.java`
      (new) calls that method directly, the way `BoundedWaitTest` tests the bound.
      *Mutant that must red it:* revert to `List.of()` with no `error` key. The
      failure and empty cases then produce the same map and
      `failureAndEmptyAreDistinguishable` fails.
- [ ] 1.2 `HttpApiServer` `find_entities` (`:1128-1137`): the identical change on
      the `catch` at `:1134`, answering `{entities: [...], error: "<text>"}`.
      This is the whole reason `find_entities` is in this change rather than its
      own; it is not optional padding.
      *Test:* the same test class, `entitiesFailureAndEmptyAreDistinguishable`,
      against the same static method with the `entities` key.
      *Mutant that must red it:* revert `:1134` to `List.of()` with no `error`
      key while leaving `find_blocks` fixed. The `find_blocks` tests stay green
      and only the `entities` test reddens — which is the point: it proves the
      entity half is separately covered rather than riding on the block half.
- [ ] 1.3 Keep both log lines. `AIPlayerMod.LOGGER.error("findBlocks error", e)`
      at `:1124` and `("findEntities error", e)` at `:1134` MUST remain at error
      level with the throwable. A fix that tells the caller but drops the
      server-side log loses the operator's only view.
      *Test:* assert the answer's `error` text carries the exception type, which
      is what the agent's normaliser keys on; if a logging seam exists, assert
      the call too.
      *Mutant that must red it:* delete the `LOGGER.error` call while keeping the
      `error` key. If no seam asserts the log, this mutant is NOT caught and that
      must be said in the task's completion note rather than implied.
- [ ] 1.4 Success paths unchanged for both verbs. Not its own edit; it is the
      constraint on 1.1 and 1.2.
      *Test:* `successPathIsUnchanged` asserts `{blocks: [<two blocks>]}` and
      `{entities: [<two entities>]}` carry exactly their list key and nothing new.
      *Mutant that must red it:* add an `error` key to the success map. The test
      must redden; a test that would tolerate an extra key is not pinning the
      promise.

## 2. Agent: one rule for both verbs, pinned at the seam

The agent code is already live (`agent/script_tick.py:_normalise_query_result`,
present at `origin/main` and at `2f019c0`, guard at `:660`). Nothing here changes
it; these tasks prove it reads the mod's new answer. **One scenario covers both
verbs** (reviewer: do not write two) because the normaliser reads the `error` key
without knowing which verb produced it.

- [ ] 2.1 `agent/test_script_tick.py`: drive the mod's real failure answers
      `{blocks: [], error: "findBlocks error: ..."}` and
      `{entities: [], error: "findEntities error: ..."}` through
      `_normalise_query_result` and assert (for each) `ok is False`,
      `reason == "error"`, `message` carries the mod's text, `matches == []`.
      Add the twins: `{blocks: []}` and `{entities: []}` with no error key stay
      `ok is True, matches == []`.
      *Mutant that must red it:* delete the guard at `agent/script_tick.py:660`
      (`if value.get("error") not in (None, "", False):`). Both failure cases then
      report `ok=True`. **Run it and record the tally** with the exact
      invocation; at `9a8a083` it reddened exactly
      `test_an_answer_marked_failed_is_not_reported_as_a_success`, so confirm the
      count against the new twins or explain the new number.
- [ ] 2.2 `agent/test_script_tick.py`: run declared `blocks` and `entities`
      queries through `run_declared_queries` with the api returning the mod's
      failure maps, asserting each installed `look.queries.<name>` is
      `{ok: false, reason: "error"}` and its siblings are untouched.
      **A test whose fake `find_blocks`/`find_entities` raises does NOT satisfy
      this** — it proves the transport's `except` branch, not the error-key path,
      and the guard could be deleted with the suite still green.

## 3. Comment hygiene, in the commit that lands the mod fix

- [ ] 3.1 `agent/script_tick.py:628-635` narrates the swallow as
      `HttpApiServer:1123-1126` and speaks of `find_blocks` alone. At `bf560d2`
      the catch is `:1124` and the send is `:1126`; `:1123` is the `try`. Both
      the range and the singular verb go stale with this change, and the
      "Until then…" clause stops being true once an error key ships.
      *Test:* none; `python3 -m py_compile agent/script_tick.py` and the suite.
- [ ] 3.2 The `api-http` delta's `HttpApiServer:1117-1127` cite (`:16`) is correct
      at `bf560d2` and stays correct. Do not edit it.

## 4. api-http delta: BLOCKED on the A/B/C answer

The `api-http` ADDED requirement (`A Failed Block Search Answers With An Error,
Not A Bare Empty List`) and its five scenarios name `/find_blocks` only. With
`find_entities` in scope, the `:1134-1136` change would ship with no api-http
requirement stating what its answer must be. Row
`qitem-20261127115907-7364ff65543d072d` asks reviewer and lead to pick A, B or C.
- [ ] 4.1 Resolve A/B/C. Do not start 4.2 before it is answered.
- [ ] 4.2 If A or B: add the entity requirement/scenarios. If C: remove 1.2 and
      1.3's entity half and file it separately.

## 5. Verification

- [ ] 5.1 `./gradlew :test --tests '*FindBlocksFailure*' --rerun --no-build-cache`
      with `-Xmx2g`, `--max-workers=2`, `nice -n 19`. Read the JUnit XML tally;
      `FROM-CACHE` is not a run.
- [ ] 5.2 From inside `agent/`: `python3 -B -m unittest test_script_tick`. Report
      `Ran N` and `OK` from stderr with the cwd and command. `-B` so a stale
      `.pyc` cannot re-run the unmutated module under a mutant.
- [ ] 5.3 `openspec validate find-blocks-reports-failure --strict` returns rc=0
      "valid" — recorded, but it does NOT prove the delta type. It counts
      ERROR+WARNING; an ADDED-only delta that should be MODIFIED is INFO. The
      type is proven by the scenario check below.
- [ ] 5.4 Delta type check, run and record the output: the delta must carry all
      7 live scenarios of `bot-coded-agents/spec.md:1619` **verbatim** (bodies,
      not just names) plus the 3 new ones. Measured once already: 7 carried, 0
      missing, 3 new, intro paragraph identical. Re-run it at the committed rev.
- [ ] 5.5 Archive `find-blocks-reports-failure` only after landing and review.
      `script-lookups-and-results` is ALREADY archived on `origin/main`
      (`bf560d2`), so there is no ordering constraint left — the superseded
      task 3a is void. After archiving,
      `grep -c "A Script Declares The Searches" openspec/specs/bot-coded-agents/spec.md`
      MUST be 1.
- [ ] 5.6 End-to-end, on a test server: a search that throws in a live world
      reaches `look.queries.<name>` as `{ok: false, reason: "error"}` for both a
      `blocks` and an `entities` query. This is a deploy-run-plan check, not a
      JUnit test; record the command and its output in the deploy notes.
