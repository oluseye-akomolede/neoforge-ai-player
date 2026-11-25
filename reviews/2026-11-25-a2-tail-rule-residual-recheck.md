# A2 residual re-check — `510dd08`

**Row:** `qitem-20261125043633-8683cec2ec0065e3`.
**Verdict:** **PASS.** The no-semicolon residual is closed, the multi-line block-comment hazard is
closed and spec'd, and the spec now describes what the parser does on every shape I probed. One
shape I probed is left open deliberately (below) — it is not a code defect.

Read from a clean `git archive 510dd08` in `/tmp/a2-r3`; mutants on copies; all probes `-I`.

## What changed

The two tail paths are one loop (`script_tick.py`, after the closing `]`):
`_skip_ws_and_comments` no longer runs first — that skip was **my** finding's cause, and the builder
is right that it ate the newline. On the terminator line only ` \t\r;` and comments advance; the
first `\n` ends the rule; any other character refuses. A block comment containing `\n` refuses
rather than being treated as the line break.

That origin difference is worth recording: before the semicolon there was no
trivia-skip-then-decide path to reach the bug, so the `];` forms looked correct while the
no-`;` forms disagreed with the spec.

## Shape matrix — 21 probes, one open by design

Every spec'd shape behaves as the spec states now:

| Shape | Result |
|---|---|
| `]` then code next line / at EOF / EOF | ACCEPT |
| `];` then code next line / at EOF | ACCEPT |
| `];` CRLF then code; `];` trailing spaces then code | ACCEPT |
| `] // why` then code (no `;`) — the residual | **ACCEPT** (was REFUSE) |
| `] /* why */` then code (no `;`) | ACCEPT |
| `]; // why` then code; `]; /* why */` then code | ACCEPT |
| `] evil()`, `] /*x*/ evil()`, `]; /*x*/ evil()` | REFUSE |
| `]; evil()`; `;; evil()`; `+ evil()`; `, evil()` | REFUSE |
| `]; /* a` NL ` */ evil()` (the builder's near-miss) | REFUSE |
| `] /* a` NL ` */` then code | REFUSE |
| unterminated `/*` after `];` | REFUSE |

**Open by design — `]; api.log(1)` on one line is REFUSED.** I listed that in my probe as "legal"
and it is not: the spec says anything but spaces/tabs/`\r`/`;`/comments on the terminator line is
refused, and a call is not. The refusal is right, my label was wrong. Not a defect.

## Mutants

I rebuilt both on copies of the module:

- **M1 — reinsert the skip-then-decide.** Reds `test_the_tail_rule_holds_with_and_without_the_terminator`
  (`Ran 35, FAILED (errors=1)`), and the shape matrix independently catches three accept-cases
  collapsing to REFUSE (`]` then code, `] // why` then code, `] /* why */` then code). So the
  pinned shape test and the probe agree — this is a test **and** an independent check.
- **M2 — drop the multi-line-refusal.** Reds `test_a_block_comment_may_not_carry_the_statement_across_a_line`
  (`FAILED (failures=1)`), and the shape matrix catches `] /* a` / `*/` then code turning ACCEPT.
  Both caught the same way; no surviving mutant in the shapes I probed.

Clean module: `test_declared_queries Ran 35, OK` — matches the claim of 35.

## Spec delta

The sentence is no longer a paraphrase of the code: `;` optional, one-or-more `;`, only
spaces/tabs/`\r`/comments on the terminator line, first line break ends the statement, comment MUST
NOT span a line with `]; /* a` / ` */ evil()` as the named measured example. I checked the delta
against the code rather than reading each in isolation: every shape on the matrix is described by
that paragraph. `openspec validate --strict` is what the builder ran; the spec I re-read at the rev
is consistent.

## What I did not do

No live bot, nothing deployed. `test_declared_queries`, and the shape matrix, only — the other three
suites the builder cites (`test_script_tick` 66, `test_result_delivery` 5, `test_agent_script_branch`
126) are unaffected by this parser-only change, and I did not re-run them; their earlier green at
`d83ca63` plus an unchanged call surface is the basis, not a fresh run.

## Repro

```
mkdir -p /tmp/a2-r3 && git -C <repo> archive 510dd08 | tar -x -C /tmp/a2-r3
# M1: insert `after = _skip_ws_and_comments(source, after)` before the tail loop
# M2: change `if "\n" in source[after:j]:` to `if False:`
python3 -I .review-verdicts/a2-probe3.py /tmp/a2-r3/agent
```
