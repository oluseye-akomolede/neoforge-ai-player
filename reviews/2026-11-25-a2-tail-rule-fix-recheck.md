# A2 F-1/F-2 re-review — `d83ca63` (neoforge-ai-player @ minecraft-wt-deepseek)

**Row:** `qitem-20261125043633-8683cec2ec0065e3` (reopened by the builder's fix notification).
**Verdict:** **F-1 PASSES, F-2 PASSES — ship it.** One residual, minor, fails-closed: the spec
still describes a kind of comment the parser does not accept, on the one sentence that isn't
exercised by a test.

Read from a clean `git archive d83ca63` in `/tmp/a2-fix`; all probes on that extraction, `-I`.

## F-1 — the `; evil()` gap is closed. PASS.

The rule now treats the terminator as the END OF A STATEMENT and keeps looking to the end of the
line. Measured on the fixed module:

| Source | Old | New |
|---|---|---|
| `queries = [...]; evil()` | ACCEPT | **REFUSE** |
| `queries = [...]; /*x*/ evil()` | ACCEPT | **REFUSE** |
| `queries = [...];; evil()` | ACCEPT | **REFUSE** |
| `queries = [...];` | ACCEPT | ACCEPT |
| `queries = [...];` then code on the next line | ACCEPT | ACCEPT |
| `queries = [...];\r\n` then code | ACCEPT | ACCEPT |
| `queries = [...];   ` then code | ACCEPT | ACCEPT |
| `queries = [...] + evil()` / `, evil()` | REFUSE | REFUSE |

`test_a_full_declaration` (its `];` then `api.log` input) is untouched and still green.

Mutants, run by me on copies of the module, not accepted from the report:
- **M1** — drop the same-line refusal: **`test_code_after_the_terminator_on_its_own_line_is_refused`
  FAILS** (only that test; `Ran 32 tests, FAILED (failures=1)`).
- **M2** — make a `//` comment consume its newline (the old F-2 behaviour): **`test_a_comment_on_the_terminator_line_before_code_is_allowed`
  ERRORS** (only that test; `Ran 32 tests, FAILED (errors=1)`).
Both mutants red what the builder said they would red, and nothing else. The new tests carry their
weight.

## F-2 — the reported case is fixed. PASS, with one residual.

`]; // why` then code on the next line is now **ACCEPTED** (it was refused). So is `]; /* why */`
then code. Good.

**Residual (minor).** The *bracket-without-semicolon* forms are still refused:

| Source | Result |
|---|---|
| `queries = [...] // why` then code | REFUSE |
| `queries = [...] /* why */` then code | REFUSE |
| `queries = [...]` then code (no comment) | REFUSE |
| `queries = [...] // why` at EOF | ACCEPT |
| `queries = [...]` at EOF | ACCEPT |

So a comment without a semicolon is legal only if it is the last thing in the file, exactly the
F-2 shape the first commit had and the one I flagged. The *cause* is shared with the `;` path, in
`_find_declaration`:

```python
rest = _skip_ws_and_comments(source, m + 1)   # this skips newlines too
if rest < n:
    if source[rest] not in ";\n":
        raise ...   # lands on line 2's code, not on the newline
```

`_skip_ws_and_comments` (unchanged, `:164-182`) skips `\n` like any other whitespace, so for the
no-semicolon forms the scan crosses to the next statement's code and the tail check refuses it.
The semicolon path is **not** affected: `]; // why` is accepted because the `;` → in-tail-loop
branch was rewritten to stop *before* the newline; the same rewrite was not made to the leading
`rest` computation.

**Does this matter?** It fails *closed* — it refuses a valid script, so a bot loses its declared
queries and falls back to a full scan; it cannot let unvalidated code run. The spec sentence
"`]; // why` followed by code on the next line stays legal" is satisfied for the `;` form and not
for the no-`;` form. `]; // why` at EOF is legal, so the comment itself is not the problem — only
the newline that follows it.

**Coverage.** The new `test_a_comment_on_the_terminator_line_before_code_is_allowed` uses
`]; // why` and `]; /* why */`, both with the semicolon, so it cannot see the bracket-only shape.
If the spec's intent is that the comment rule is about comments and not terminators, add the
no-semicolon variants; if it's that a declaration must be immediately terminated before any
placement of code, put the word `;` in the spec sentence. Pick one — right now the spec and the
code disagree on a case nobody tests.

**One more thing I could not exercise:** the multiline `/* why\n*/` after `];` is refused by the
new "same line" check (`if "\n" in source[after:j]`). That matches the comment's own reason ("skip
comments on the same line") but not the spec sentence, which does not say "same line" — the delta
does not describe what the code does for a block comment spanning lines. Low risk: fails closed.

## Test tallies, reproduced at `d83ca63`

- `test_declared_queries`: **32 tests, OK**. `test_script_tick` **66**, `test_result_delivery` **5**,
  `test_agent_script_branch` **126** — matches the builder's numbers when each is run as its own
  module from `agent/`.
- Full single-process discovery at `d83ca63`, **no `ulimit -v`** (per the owner rule for Node):
  `Ran 744 tests, FAILED (failures=30, errors=1, skipped=1)`. All 30 failures are
  `test_scout_script`; every one fails with `agent-script-runner not found (set
  AGENT_SCRIPT_RUNNER)` — the test **refuses to skip** and reds instead, so a skip can't hide it.
  With `AGENT_SCRIPT_RUNNER=/home/sigmastrain/minecraft/agent-script-runner`:
  **`test_scout_script Ran 27, OK`**. The 1 error is `dashboard` importing `uvicorn`, a missing
  dep in this extraction. So the suite is green once the runner is wired — no code failure here.
- **Correcting my own earlier review (`fb185c0`).** I reported the 30/1 as "pre-existing
  cross-module contamination, reproduced at the parent." That proved only that the *failure set*
  predates A2; it did **not** identify the cause. It is `AGENT_SCRIPT_RUNNER` unset in my archive
  extraction (and, in a separate run, `ulimit -v` killing the spawned Node under the VA cap). The
  A2 verdict and its findings stand; the causal sentence in `fb185c0` was wrong and this corrects it.

## What I did not do

No live bot, nothing deployed. Read-only probes against a clean archive of the fix rev.

## Repro

```
mkdir -p /tmp/a2-fix && git -C <repo> archive d83ca63 | tar -x -C /tmp/a2-fix
python3 -I -c 'import sys; sys.path.insert(0,"/tmp/a2-fix/agent"); import script_tick as st;
Q="[{name: \"c\", kind: \"blocks\", id: \"minecraft:chest\"}]";
try: st.parse_declared_queries("queries = "+Q+" // why\napi.log(1)")
except st.DeclaredQueriesError as e: print("REFUSE", e)'   # prints REFUSE (spec says legal)
```
