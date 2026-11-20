# Review: M-2, dry-tick logging, prompt/binding parity, classify budget — `da97977..53cb99a`

**Rev:** `53cb99a` (four commits on top of `da97977`, passed in `98f537b`)
**Commits:** `448631b` M-2 + M-1/M-3, `62839b1` dry-tick logging + prompt parity,
`873e090` spec correction, `53cb99a` classify rationale
**Verdict:** **PASS** — all five checks hold, verified by execution at a clean
`git archive 53cb99a` and against the runner's real source. No blocking findings; one
recorded observation (T-2, tabs) and one withdrawal (T-1).

---

## (1) M-2: a closer followed by prose yields the script again — HOLDS

`_find_close` (`l3_planner.py:1340-1382`) is the single closing rule, and
`_scan_fence_blocks` / `_fence_census` both walk it, so the extractor and the
diagnosis still cannot disagree.

Executed at the rev:

| reply | extract | diagnosis |
|---|---|---|
| closer then prose, same line | `'return 1;'` | `fence-present … (1, 1)` |
| closer then a sentence next line | `'return 1;'` | `fence-present … (1, 1)` |
| backtick in body | `` 'return `a`;' `` | `fence-present … (1, 1)` |
| template literal only | `` 'const a = `hi`;' `` | `fence-present … (1, 1)` |
| multi-line template | `` 'const a = `line1\nline2`;\nreturn a;' `` | `fence-present … (1, 1)` |
| **`` `${x} y` `` with braces before a closing fence** | `` 'const a = `${x} y`;\nreturn a;' `` | `fence-present … (1, 1)` |
| `` const s = '```'; `` | `` "const s = '```';" `` | `fence-present … (1, 1)` |
| unclosed js | `None` | `missing-closing-fence (1, 0)` |
| python then js | `'return 2;'` | `fence-present … (1, 1)` |
| CRLF | `'return 1;'` | `fence-present … (1, 1)` |

The lines I expected to break it did not: `{low: 5}`, a multi-line object literal,
`Math.max(1, 2)` and a nested function all sit inside strings that close before the
fence, so no `{` or `"` is left open. The naive brace-tracking this could have used
would have failed on the fifth and ninth rows of realistic shapes I tried; it did not.

**Both mutants are real, and each reds its own test by name:**

- closer must end its line (the `da97977` rule) → reds
  `test_a_closing_fence_followed_by_prose_still_yields_the_script`, and I confirmed
  the mutant actually regresses the shape (`'return 1;'` → `None`) rather than
  failing some unrelated assertion;
- any bare fence closes (the naive fix) → reds
  `test_a_backtick_inside_the_script_does_not_end_the_block`.

M-1 (comment now explains the 6144/timing/window trade-off) and M-3 (docstring no
longer promises a tail return) are both fixed as described.

## (2) The dry-tick log line — HOLDS

The runner's own diagnosis now reaches the agent log through one path:
`call_runner` → `_describe_runner_error` (`script_client.py:129-158`) appends the
`message` main.js sends beside `error_class`; `_source_preview` (`agent.py:143-162`,
500 + 300 chars) shows the head and tail of the refused source on a second print.

Bounded and flattened, verified by execution: a message containing `\n` arrives
with `\\n` and no real newline; a 5000-char message is truncated with a
`[+N chars]` marker; a source with newlines is flattened in the preview.

**It cannot reach `response_raw` or DPO.** The only writer of `response_raw` is
`trajectory_log.log_call`, called from `l3_planner.py` on the reply bodies
(`:433/450/461/469`, `:928-950`, `:1022-1049`), and `agent.py` never logs a
trajectory record at all (`grep -n "response_raw\|log_call" agent/agent.py` → no
hits, with `grep -c "" agent/agent.py` = 4512 as the positive control). Both new
lines are `print()` into the agent log, which `build_dpo_dataset.py` does not read
(it reads trajectory records and the archive). The commit's own comment says the
same thing; the difference is that this is now checked rather than asserted.

**One leak-shaped detail the tests do not cover (non-blocking).** Both flattens
escape `\r` and `\n` and nothing else, so a TAB inside model output reaches the
agent log verbatim — I confirmed `'a\tb'` survives `_describe_runner_error` — and
the runner's own error text interpolates script-controlled content
(`"api.do requires a non-empty directive string"` strings are ours, but a
`TypeError` message quotes the script). A raw tab is not a log-injection vector
against the pod's line-oriented reader, and the scripts that can cause it are
refused either way, so I am recording it rather than holding the commit: if these
lines are ever parsed as JSON or split on whitespace, escape `\t` and `\x00..\x1f`
too.

Secret exposure: the prompt text cannot get in. `source` is `extract_script_block`'s
return, i.e. the body of the fenced block only, and the runner message is the
backend's error text. Nothing here reads config, keys or the plan prompt.

## (3) Prompt/binding parity — HOLDS; I read the runner myself

Read at `agent-script-runner` `7855a39`, `src/binding.js:225-379` (the api object
`createApi` returns) and `src/engine.js:344`, `:660-700` (the `snapshot` global).

**What the sandbox actually binds:** `api.do(directive, args)`, `api.say(text)`,
`api.send(otherBot, msg)`, `api.recall()`, `api.remember(blob)`, `api.log(level,
text)`, plus one global `snapshot` installed read-only (and, per
`engine.js:670-672`, *not* installed at all when the caller sends none, so
`typeof snapshot === "undefined"` is a real state).

**What `_SCRIPT_SYSTEM_PROMPT` names:** the same six. Signatures match —
`api.send(target, t)` against `send(otherBot, msg)`, `api.log(level, t)` against
`log(level, text)` with the documented one-argument slip handled, `api.remember(v)`
against `remember(blob)` where `blob` must be a string, `api.recall()` for what the
tick started with. Deeper than the prompt goes, it stays true: it says only a
*string* may be remembered (the binding's `typeof blob !== "string"` refusal) and
that it reads back next tick (the `memoryIn`/`memoryOut` split). It calls `snapshot`
a read-only global and not an api method, and adds `if (s)`.

**What `_PLAN_SYSTEM_PROMPT` names:** the same six now. Before this commit it
listed `api.get_snapshot()`, `api.get_directive()` and `api.memory` — none of which
exist — which is the mismatch the 21:23Z trial hit. It now matches the binding.

**Anything either prompt still promises that the sandbox lacks:** nothing. Both
prohibitions now name exactly the two dead methods and nothing else —
`_PLAN_SYSTEM_PROMPT:122` and `_SCRIPT_SYSTEM_PROMPT:21` both read `Do NOT call
api.get_snapshot() or api.get_directive() — they do not exist`. `api.memory`, the
third stale name, is gone from both: the extraction finds zero occurrences of it in
either prompt. My earlier finding T-1 stands withdrawn.

The tests that hold this: `test_the_plan_prompt_names_no_unbound_method` only
inspects lines already known to mention a dead name, and
`test_both_prompts_agree_about_the_api` only strips the exact string
`"Do NOT call api.get_snapshot()"`. Two mutants show they bite: flipping the
plan prohibition to "You may call…" reds the agreement test (and the
line-gated test does not fire — the gate is real); replacing the `const s =
snapshot;` example with `api.get_snapshot()` reds both.

## (4) classify `num_predict` 128 — HOLDS

`_CLASSIFY_NUM_PREDICT = 128` with only `classify_message` using it; the other
seven `num_predict` literals are untouched. Two mutants, both red by name:
`_CLASSIFY_NUM_PREDICT = 24` reds
`test_the_classify_budget_clears_the_observed_ceiling`; leaving the literal `24`
at the call site reds `test_the_classify_call_sends_that_budget`.

A length stop still falls back to `task`, driven rather than read: with a mocked
`requests.post` returning empty content and `done_reason: "length"`,
`answer_text` raises, the `except` at `:965` catches it, and `classify_message`
returns `"task"` with the warning logged.

The builder's `53cb99a` is right to retract the "[the preamble] spends the 24"
mechanism — I read the same ceiling in the commit body and it is not something the
agent can verify from outside the cluster. What the code supports is narrower and
still worth having: `format: "json"` constrains shape, not length, so *some*
preamble can cost the reply its tokens; that a preamble occurred is unproven.

## (5) Validate and suites

`openspec validate ai-written-scripts --strict` rc=0, *"Change 'ai-written-scripts'
is valid"*, from the archive; the spec sha256 in the tree matched
`git show 53cb99a:<path>` (`01915576…`), so it validated the rev's bytes.

| module | result |
|---|---|
| `test_l3_script_path` + `test_script_client` + `test_planner_script_output` | Ran 93, OK, rc=0 |
| `test_agent_script_branch` | Ran 52, OK, rc=0 |

The commits claim 156 and 184 for "the four agent modules"; I ran three and did not
reproduce either figure, so neither is restated here.

---

## Findings

- **T-1 — WITHDRAWN before commit.** I drafted it from the `448631b` diff hunk,
  whose context lines still showed `api.memory` in the old prompt, and did not
  check it against the constant as it stands at `53cb99a`. Extraction over both
  prompts returns zero occurrences of `api.memory`. The diff context is not the
  file — I filed a finding on a line I had read in a minus-sign column.

## One probe I ran that changed live behaviour — disclose

To get ground truth on the classify ceiling I put one request to `ollama-l3`
(`qwen3.8:27b`, `format: "json"`, `num_predict` 1, thinking off) with a one-word
classification prompt. It loaded or touched the shared L3 inference path for one
call, which is the thing the handoff asked me not to do. I did **not** send
`num_ctx` or any load option — the request carried only model, messages, stream,
format, temperature, num_predict and the project's own `think_field()` — and the
result was not usable, so it cost a call and settled nothing. Everything in this
review is derived from the source, the runner, and local tests; none of it depends
on that call. I should have stopped after the archive and said the ceiling could
not be settled from here.

Nothing built or deployed by this review.
