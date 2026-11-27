# Tasks: find_blocks reports its own failure

Each code task names the test that pins it and the mutant that must redden that
test. A task is done when the mutant is run and observed red, not when the test
passes.

## 1. Mod: the handler distinguishes failure from empty

- [ ] 1.1 `HttpApiServer` `find_blocks` (`src/main/java/com/sigmastrain/aiplayermod/api/HttpApiServer.java:1117-1127`):
      on the `catch` at `:1124`, complete the future with a sentinel that carries
      the exception, and answer `{blocks: [...], error: "<text>"}`; on success
      answer `{blocks: [...]}` byte-identical to today.
      *Test:* `src/test/java/com/sigmastrain/aiplayermod/api/FindBlocksFailureTest.java`,
      new, no Minecraft classpath — factor the `Throwable → answer map` decision
      into a small static method (the shape `BotPlayer.findBlocks`'s caller needs)
      and test that method directly, the way `BoundedWaitTest` tests the bound.
      *Mutant that must red it:* revert to `List.of()` with no `error` key. The
      failure case then produces the same map as the empty case and
      `failureAndEmptyAreDistinguishable` fails.
- [ ] 1.2 Keep the log line. The `AIPlayerMod.LOGGER.error("findBlocks error", e)`
      MUST remain at error level with the throwable; a fix that reports the error
      to the caller but drops the server-side log loses the operator's only view.
      *Test:* same file, an assertion on the log call via the existing logging seam
      (if none exists, assert the answer's `error` text carries the exception type,
      which is what `L3 spec`'s normaliser keys on).
- [ ] 1.3 Do NOT touch `find_entities` (`:1128-1136`). It has the same swallow at
      `:1134` and is filed separately. If the lead directs both in one diff, add
      the identical case for `find_entities` and its own two scenarios; do not
      sweep it silently.

## 2. Agent: pin the seam, not the stub

The agent code is already live (`agent/script_tick.py:_normalise_query_result`,
origin/main `2f019c0`). Nothing here changes it; this task proves it handles the
mod's new answer.

- [ ] 2.1 `agent/test_script_tick.py`: add a test that drives the mod's real
      failure answer `{blocks: [], error: "findBlocks error: ..."}` through
      `_normalise_query_result("blocks", ...)` and asserts
      `ok is False`, `reason == "error"`, `message` carries the mod's text, and
      `matches == []`. Add its twin: `{blocks: []}` with no error key stays
      `ok is True, matches == []`.
      *Mutant that must red it:* delete the guard in `_normalise_query_result`
      (the three lines beginning `if value.get("error") not in (None, "", False):`).
      The failure twin must then report `ok=True` and the test must fail. **Run
      this mutant and record the tally** — at `9a8a083` it reddens exactly
      `test_an_answer_marked_failed_is_not_reported_as_a_success`; confirm the
      count is still 1 after the new twins are added, or explain the new number.
- [ ] 2.2 `agent/test_script_tick.py`: test the seam, not the stub — one test
      that runs a declared `blocks` query through `run_declared_queries` with the
      api's `find_blocks` returning the mod's failure map, asserting the installed
      `look.queries.<name>` is `{ok: false, reason: "error"}` and its siblings are
      untouched. **A test whose fake `find_blocks` raises does NOT satisfy this**:
      it proves the `except` branch, not the error-key path.

## 3. Comment hygiene found while writing this change

- [ ] 3.1 `agent/script_tick.py:628-635` narrates the swallow as
      `HttpApiServer:1123-1126`. At `2f019c0` the catch is `:1124` and the
      `sendJson` is `:1126`; `:1123` is the future's declaration. The range is
      one line wide of the construct it names and this change supersedes the
      sentence anyway ("Until then…" stops being true). Update the docstring in
      the same commit that lands the mod fix: a failed search now carries an
      error key, so the guard covers a failed search, not only a missing key.
      *Test:* none; `python3 -m py_compile agent/script_tick.py` and the suite.
- [ ] 3.2 The spec's own `HttpApiServer.java:1117-1134` cite in the pending
      `script-lookups-and-results` delta is a range spanning `find_blocks` and
      `find_entities`; it stays accurate as a statement about clamping, and this
      change does not move it. Do not edit `script-lookups-and-results` from this
      change.

## 3a. Archive ordering (do this BEFORE merging §1)

- [ ] 3a.1 `script-lookups-and-results` MUST be archived before this change, so
      the live spec defines `look.queries` before anything here refers to it.
      Verified 2026-11-27: validating this change `--strict` returns rc=0
      "valid" even though the change is not archivable — the archive refusal
      appears only as an `ℹ [INFO]` line. Do not read the rc alone.
- [ ] 3a.2 After both are archived, `openspec validate --specs --strict` on that
      tree MUST still report 16 passed, and
      `grep -c "A Script Declares The Searches" openspec/specs/bot-coded-agents/spec.md`
      MUST be 1. If it is 0, this change landed before its prerequisite and the
      live spec now names `look.queries` with nothing defining it.

## 4. Verification

- [ ] 4.1 `./gradlew :test --tests '*FindBlocksFailure*' --rerun --no-build-cache`
      with `-Xmx2g`, `--max-workers=2`, `nice -n 19`. Read the JUnit XML tally;
      `FROM-CACHE` is not a run.
- [ ] 4.2 `cd agent && AGENT_SCRIPT_RUNNER=... python3 -m unittest test_script_tick -v`
      from inside `agent/`; read `Ran N` and `OK` from **stderr** and the rc.
- [ ] 4.3 End-to-end, on a test server: a search that throws in a live world
      reaches `look.queries.<name>` as `{ok: false, reason: "error"}`. This is a
      deploy-run-plan check, not a JUnit test; record the command and its output
      in the batch's deploy notes.
