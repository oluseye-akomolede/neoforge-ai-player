# Review: a2 fence diagnosis state walk — `e83b074` + `f16a04b`

**Range reviewed:** `cd781c1..f16a04b` (`e83b074` fix, `f16a04b` tests) — the lead's scope, 19:31Z.
**Row:** `qitem-20261120191732-936dc02555828d80` (reopened 19:44Z; my `cd781c1` PASS at review `8738988` ran
before these landed, so it did not cover them).
**Prior:** `059c74d` NOT YET (review `e1f1bdf`), F1 = the close count is not attributed to a block; F2 = the test
at `:995` asserts `closed 2` under a docstring saying "exactly one js close".
**Verdict:** **PASS** for the fence fix. F1 and F2 are both closed — the state walk is the right fix and the four
rows report true counts. Two second-order defects are recorded below; neither is caused by this diff and neither
is a reason to hold it.

---

## F1 — fixed, executed

The independent `re.findall` tally is replaced by an in-order walk with an `inside_js` flag; a close counts only
when the fence that terminates an open js block is bare. Run at `f16a04b` against my four rows from `e1f1bdf`:

| Reply | `059c74d` said | `f16a04b` says | true |
|---|---|---|---|
| python + js, both closed | `opened 1, closed 2` | **`opened 1, closed 1`** | 1 |
| python + python + **unclosed** js | `opened 1, closed 2` | **`opened 1, closed 0`** | 0 |
| bare fence + **unclosed** js | `opened 1, closed 2` | **`opened 1, closed 0`** | 0 |
| python + **unclosed** js | `opened 1, closed 1` | **`opened 1, closed 0`** | 0 |

Rows 2–4 now take the `missing-closing-fence` branch, which is the right advice for them — the script is fine
and the close is missing. `inside_js` also carries a genuinely better signal than the count: an unterminated
block is reported missing whatever the arithmetic says.

Edge shapes I tried, all sane: `js` closed then `python` → usable, closed 1; two closed js blocks → opened 2,
closed 2; a second tagged fence inside an open js block → missing, closed 0; `javascript`, uppercase `JS`, CRLF,
and no fences at all each behave. `extract_script_block` still returns a block exactly for row 1.

## F2 — fixed

The four rows are now `ROW_1..ROW_4` fixtures with the expected js-close count in the name and docstring, each
asserting both numbers, and the wrong `closed 2` is gone. Of the four, three are reds on the old tally — and the
one that is not is the useful one:

- **Mutant that reopens F1** — treat any fence inside a js block as its closer (the python-closer defect): red
  on `test_a_second_js_fence_while_one_is_open_is_not_a_close`.
- **Mutant that puts back `059c74d`'s bare ` ```([^\n]*) `** — every fence anywhere, tags and trailing prose
  included: **survives 51/51.** The state machine makes the tolerant regex harmless on the four rows, and the
  sweep moved that mutant from footnote to irrelevant.

Suite at `f16a04b` from a clean `git archive`: `Ran 51 tests … OK`, rc=0 (47 from `cd781c1` plus 4 net new).

---

## G-4 (pre-existing, not this diff) — the diagnosis and the extractor disagree about a trailing fence

`extract_script_block` accepts a closer followed by anything: ` ```js\nreturn 1;\n``` ` (trailing space),
` ``` … ``` extra prose `, even ` ``` … ```js `. The diagnosis walk requires the fence to be alone on its line
(`[A-Za-z0-9_+.-]*[ \t]*\r?(?=\n|$)`) and so does not see those as closers:

| reply | extractor | `fence_diagnosis` |
|---|---|---|
| ` ```js\nreturn 1;\n``` extra prose ` | returns `return 1;` | not a closer → `missing-closing-fence (opened 1, closed 0)` |

That row is not reachable through `call_script`, because the script is returned before the diagnosis runs
(the warning is for the `script is None` case). The one reachable shape is a reply whose js block is unterminated,
followed by a non-js block that closes at the very end or has trailing prose: the extractor then rejects (its
regex matches `javascript`/`js` opens only) and the diagnosis says `missing` when the trailing fence does close
it. Low impact — the log line is still a log line — but if the diagnosis is going to be trusted to name the cause,
it and the extractor should agree about what a fence is. The new single regex is the natural place to share.

## G-3 (carried) — a truncation that leaves content binds the partial script

Unchanged by this range and still the sharpest thing outstanding against `ai-written-scripts:683-691`. The new
requirement says *"A truncated reply MUST remain 'no script' rather than a partially-bound program"* and *"the log
MUST name truncation as the cause, distinct from a malformed or missing fence."* Both hold only when the
truncation leaves `content` empty, because `answer_text` (`config.py:151-166`) raises only then. With `think`
off, a truncated script can still have content and no closing fence — and `_SCRIPT_FENCE_RE` is
`_SCRIPT_FENCE_RE` (`l3_planner.py:1277-1278`, ` ```(?:js|javascript)\s*\n(.*?)\n?``` `) never requires a
closer for the block it opens, so `.*?` runs to end-of-string and
the partial script is returned. Proven at `cd781c1` by driving a real 1117-char reply cut mid-block through the
rev's own `call_script`; the same code is here. The `''`-instead-of-`None` mutant also survives, so nothing pins
the refusal against a future edit.

Why this matters more now: `agent/scripts/scout.js` is **14 328 chars ≈ 3 980 tokens**. If a planner reply ever
carries prose or a thinking block in front of a script that size, it truncates with content present, the
diagnosis correctly says `missing-closing-fence`, and the partial script is bound anyway. G-3 is not a fence-count
problem — the count is right — it is the extractor not requiring the closer the diagnosis is complaining about.

---

## Not disputed

- Feature flags unchanged in this range; nothing built or deployed by this review.
- `cd781c1`'s PASS (review `8738988`) stands for the parts it covered; `cd781c1..f16a04b` touches only
  `l3_planner.py` and its test file.
