# Tasks: a failed search reports its own failure

Each code task names the test that pins it and the mutant that must redden that
test. A task is done when the mutant is run and observed red, not when the test
passes.

**Scope: both verbs.** `find_blocks` (`:1124`) and `find_entities` (`:1134`) are
fixed in this change by the lead's decision of 11:58Z. The live
`bot-coded-agents` requirement already forbids `{ok: true, matches: []}` on
failure; both sites violate it today.

**Delta type: MODIFIED.** `script-lookups-and-results` is already archived
(`bf560d2`), so the `bot-coded-agents` requirement is live at `:1619`. This change
modifies it — 7 live scenarios carried verbatim by substitution + 3 new = 10. An
ADDED-only delta would strand the existing seven.

## 1. Mod: both handlers distinguish failure from empty

- [ ] 1.1 `HttpApiServer` `find_blocks` (`:1117-1127`): on the `catch` at
      `:1124`, complete the future with a sentinel carrying the exception, and
      answer `{blocks: [...], error: "<text>"}`; on success answer
      `{blocks: [...]}` byte-identical to today.
      *Test:* `src/test/java/com/sigmastrain/aiplayermod/api/FindSearchFailureTest.java`,
      new, no Minecraft classpath — factor the `Throwable → answer map` decision
      into a small static method and test that method directly, in the shape
      `BoundedWaitTest` establishes.
      *Mutant that must red it:* revert to `List.of()` with no `error` key. The
      failure case then produces the same map as the empty case and
      `failureAndEmptyAreDistinguishable` fails.
- [ ] 1.2 `HttpApiServer` `find_entities` (`:1128-1136`): the identical change on
      the `catch` at `:1134`, answering `{entities: [...], error: "<text>"}`; the
      success path stays byte-identical.
      *Test:* same new file, the entity twin of 1.1's test.
      *Mutant that must red it:* the same revert on this catch. **Run it
      separately from 1.1's mutant** — a suite that reddens on the block mutant
      proves nothing about the entity one.
- [ ] 1.3 Keep both log lines. `AIPlayerMod.LOGGER.error("findBlocks error", e)`
      and `("findEntities error", e)` MUST remain at error level with the
      throwable; reporting the error to the caller but dropping the server-side
      log loses the operator's only view.
      *Test:* same file, assert the answer's `error` text carries the exception
      type, which is what the normaliser keys on.
- [ ] 1.4 Do NOT change `scan_data` (`:1420`, already correct, and the shape
      being copied) or `surface_scan` (`:1425`, different verb, different answer).
      Do not change `boundedJoin`/`BoundedWait`; the timeout path already answers
      503 with an `error` body.

## 2. Agent: pin the seam, not the stub

The agent code is already live (`agent/script_tick.py:_normalise_query_result`).
Nothing here changes it; these tasks prove it handles the mod's new answer. The
guard is generic — it keys on the presence of an `error` key, not on the verb —
so **one** normaliser test covers both, but the seam test must use each verb's
real failure map.

- [ ] 2.1 `agent/test_script_tick.py`: drive the mod's real failure answer
      `{blocks: [], error: "findBlocks error: ..."}` through
      `_normalise_query_result("blocks", ...)` and assert `ok is False`,
      `reason == "error"`, `message` carries the mod's text, `matches == []`.
      Add its twin: `{blocks: []}` with no error key stays `ok is True,
      matches == []`.
      *Mutant that must red it:* delete the guard's three lines beginning
      `if value.get("error") not in (None, "", False):`. **Run it and record the
      tally** — at `9a8a083` it reddened exactly
      `test_an_answer_marked_failed_is_not_reported_as_a_success`; confirm the
      count after the new twins are added, or explain the new number.
- [ ] 2.2 The same pair for `entities`: `{entities: [], error: "..."}` →
      `{ok: False, reason: "error"}`, and `{entities: []}` → `{ok: True,
      matches: []}`.
- [ ] 2.3 Seam test, not stub — for each verb, run a declared query through
      `run_declared_queries` with the api returning the mod's failure map, and
      assert the installed `look.queries.<name>` is `{ok: false, reason:
      "error"}` while its siblings are untouched. **A fake that raises does NOT
      satisfy this**: it proves the `except` branch, not the `error`-key path.

## 3. Comment hygiene

- [ ] 3.1 `agent/script_tick.py`'s docstring says the guard is future-proofing
      because no query kind sends an `error` key today, and that `find_blocks`
      swallows at `:1123-1126`. After this change both halves of that are stale:
      a failed search now carries an error key, and the catch is `:1124` (the
      `:1123-1126` range is one line wide at the start). Update the docstring in
      the same commit that lands the mod fix.
      *Test:* none; `python3 -m py_compile agent/script_tick.py` and the suite.
- [ ] 3.2 Do not edit `script-lookups-and-results`; it is archived and this
      change does not move it.

## 4. Archive and verification

- [ ] 4.1 `openspec validate find-blocks-reports-failure --strict` → expect
      rc=0 "valid". **Validation passing is not evidence it is archivable** — the
      header check happens only at archive time and reports as an info line. The
      real test is 4.2.
- [ ] 4.2 Dry-run the archive in a scratch tree: the totals MUST read
      `+ 2 added, ~ 1 modified, - 0`. If it reports `- N`, scenarios were
      dropped: stop and diff the header against live `:1619`.
- [ ] 4.3 After archiving, `openspec validate --specs --strict` on that tree MUST
      pass, and the requirement's scenario count MUST be 10, not 7.
- [ ] 4.4 `./gradlew :test --tests '*FindSearchFailure*' --rerun --no-build-cache`
      with `-Xmx2g`, `--max-workers=2`, `nice -n 19`. Read the JUnit XML tally;
      `FROM-CACHE` is not a run.
- [ ] 4.5 `cd agent && AGENT_SCRIPT_RUNNER=... python3 -m unittest test_script_tick`
      from inside `agent/`; read `Ran N` and `OK` from **stderr** and the rc.
- [ ] 4.6 End-to-end, on a test server: a search that throws in a live world
      reaches `look.queries.<name>` as `{ok: false, reason: "error"}`, for both
      verbs. A deploy-run-plan check, not a JUnit test; record the command and
      output in the batch's deploy notes.
