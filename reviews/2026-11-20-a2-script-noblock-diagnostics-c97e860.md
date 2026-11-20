# Review: SCRIPT no-block diagnostics

**Rev:** `c97e860` (`agent/l3_planner.py` + `agent/test_l3_script_path.py`, +150/−2)
**Verdict:** **PASS with one non-blocking correction (N-1)** — diagnostic-only as claimed;
checks (1), (2), (4) hold; check (3) labels are right for every *pure* form, but the
`closed` count is wrong whenever the reply contains a non-js fence.

Not built, not deployed by this review.

---

## Checks

### (1) The extractor's behaviour is unchanged — HOLDS

`extract_script_block` is not touched by this commit (`git show c97e860 | grep -c '^[+-].*def extract_script_block'` → 0). The 6 new tests document the accepted forms and assert on the extractor's **result**, not its internals:

| Test | Line | Asserts |
|---|---|---|
| `test_a_javascript_fence_tag_is_accepted` | `:79` | js tag accepted |
| `test_a_closing_fence_with_no_newline_before_it_is_accepted` | `:875` | close w/o leading newline OK |
| `test_a_missing_closing_fence_is_rejected` | `:882` | `None` |
| `test_a_fence_with_no_newline_after_the_tag_is_rejected` | `:889` | `None` — the `"```js <code>"` case |
| `test_trailing_prose_after_the_fence_still_yields_the_script` | `:895` | script still extracted |

The commit body's claim that a bare `"```js <code>"` tag and a missing close are the two forms that do not match is correct, and the tests pin both.

### (2) The tail is content-only, bounded, escaped; nothing new reaches `response_raw` — HOLDS

- `response_raw` is not touched (`grep -c '^[+-].*response_raw'` → 0).
- `tail_reply` (`:1301`) takes only `raw`; both call sites pass `raw = answer_text(body)`.
- Executed: 1054-char content with embedded newline, tab, quote and backslash → output has **0** newlines, `repr()`-escaped, ends carry the marker. Bound is exact: 200 chars pass through, 201 → `[+1 chars]...` + last 200. `None` → `<no reply>`.
- Escaping matches `preview_reply`'s rule, and `preview_reply` itself is unchanged (`:1285`).

### (3) The diagnosis labels — RIGHT for pure forms, WRONG arithmetic on mixed fences

Ran 10 reply shapes. The three labels are correct for every single-fence-form reply:

| Reply | `fence_diagnosis` | extractor |
|---|---|---|
| no fence | `no-js-fence (…not found)` | `None` |
| js, no close | `missing-closing-fence (opened 1, closed 0)` | `None` |
| js, empty block | `fence-present-but-block-unusable (opened 1, closed 1)` | `None` |
| js + trailing prose | `fence-present-but-block-unusable (opened 1, closed 1)` | extracted |

**N-1 (non-blocking): `closed` over-counts when a non-js fence is present.**

`:1324` — `closes = text.count("```") - opens`. `text.count("```")` counts every fence
*marker*, so subtracting only the js *opens* leaves every non-js **opening** fence counted
as if it were a close:

```
```python
x=1
```
```js
let y=2
```
→ (opened 1, closed 3)     # there are 2 blocks; nothing is closed 3 times
```

For a pure-js reply the formula is accidentally correct, which is why the suite is green.
It is wrong exactly when the model emits any second fenced block — plausible for a reply
that shows an example first.

Why it matters: this line exists to tell the lead *which* fence failed during the 2a.9
trial. `closed 3` against `opened 1` on a reply that has one js block sends the reader
looking for fences that aren't there — the same "the preview couldn't say why" problem the
commit set out to fix.

Suggested: count closing fences directly rather than by subtraction, e.g. fence markers
not immediately preceded by a language tag. A test with a `python` + `js` pair asserting
the printed numbers would pin it; today **no assertion pins `closed` at all** — I replaced
the arithmetic wholesale and all 40 tests stayed green.

The label choice itself is sound; only the parenthetical number is unreliable.

### (4) No new exception path in `call_script` — HOLDS

`call_script` (`:1362`): `requests.post` + `resp.json()` inside `try … except (RequestException, ValueError)`; `answer_text` + `extract_script_block` inside `try … except TruncatedAnswer` → `return None` (`:1413-1418`). The new `log.warning` (`:1427`) is after both guards, `body` is in scope from `:1403`, and `raw` is a `str` from `answer_text`, so `len(raw)` cannot raise. `TruncatedAnswer` still means no-script.

---

## Tests

```
python3 -m unittest test_l3_script_path
Ran 40 tests in 0.175s
OK            # rc=0, captured without a pipe
```

40/40 matches the claim.

**Mutants reproduced first-hand** (not taken from the commit body):

| Mutant | Result |
|---|---|
| constant `fence_diagnosis` return | reds **1** — matches the builder's claim |
| replace `closed` arithmetic wholesale | **survives all 40** — see N-1 |

The second is the one I'd have wanted to see red; it is the evidence for N-1.

---

## Citation sweep at `c97e860`

| Cite | Line text | OK |
|---|---|---|
| `l3_planner.py:1281` | `_PREVIEW_CHARS = 600` | ✅ |
| `l3_planner.py:1282` | `_TAIL_CHARS = 200` | ✅ |
| `l3_planner.py:1285` | `def preview_reply(raw: str) -> str:` | ✅ |
| `l3_planner.py:1301` | `def tail_reply(raw: str, n: int = _TAIL_CHARS) -> str:` | ✅ |
| `l3_planner.py:1316` | `def fence_diagnosis(raw: str) -> str:` | ✅ |
| `l3_planner.py:1323` | `opens = len(re.findall(r"```(?:js\|javascript)\s*\n", text, re.IGNORECASE))` | ✅ |
| `l3_planner.py:1324` | `closes = text.count("```") - opens` | ✅ |
| `l3_planner.py:1332` | `def extract_script_block(model_text: str) -> str \| None:` | ✅ |
| `l3_planner.py:1403` | `body = resp.json()` | ✅ |
| `l3_planner.py:1413-1418` | `except TruncatedAnswer … return None` | ✅ |
| `l3_planner.py:1427` | warning string with `done_reason=%r eval_count=%r` | ✅ |
| `test_l3_script_path.py:927` | `def test_the_warning_names_the_missing_closing_fence(self):` | ✅ |
| `test_l3_script_path.py:942` | `def test_the_warning_includes_the_tail_not_only_the_head(self):` | ✅ |
| `test_l3_script_path.py:956` | `def test_an_unclosed_fence_at_the_very_end_shows_in_the_tail(self):` | ✅ |

---

## Scope note

`98d3db6` (stop-shortcut spec write-up) deliberately not reviewed, per the request.
Nothing here is a spec claim; this commit adds no requirement and changes no behaviour.
