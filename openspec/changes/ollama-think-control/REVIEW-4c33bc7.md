# Review: ollama-think-control implementation at 4c33bc7

Reviewer: minecraft-reviewer@minecraft
Rev under review: `4c33bc7682e36745f8d9b78d59ced993b4cf5abf`
Read from: `git archive 4c33bc7` extracted to `/tmp/rv-4c33` (not a worktree).
Spec passed at: `6d57894` (review `d0c4b1b`).

## Verdict: PASS, with one finding that does not block

The implementation does what the spec requires and what my two notes asked for. The
finding below is about the guard's reach, not about the shipped behaviour.

## What I verified myself, not from the report

- **All 12 agent /api/chat call sites carry the field.** Enumerated by AST over the
  four modules: 12 call nodes, each with exactly one `json=` keyword containing
  `think_field()`. Independent of their test.
- **All 12 response reads are routed through `answer_text`.** Enumerated by AST:
  12 functions post to `/api/chat`, each calls `answer_text` exactly once and makes
  exactly one `.json()` call. No raw `message.content` read survives in the four
  modules (`grep` for direct content reads returns nothing outside request bodies).
- **`answer_text` predicate is right.** Empty/whitespace + `done_reason=="length"`
  raises; empty + `"stop"` returns `""`; non-empty + `"length"` returns the text.
  Exercised directly against the function, both directions.
- **N1 is closed.** `make-evals-configmap.sh` emits `think` and *refuses* a
  non-`true|false` value with exit 1; `evalconfig` uses `isinstance(x, bool)` and
  refuses a quoted string or number, with `think_from_file` recording provenance.
- **Note 1 folded in correctly.** `evalconfig` refuses `think: 1` — I measured that
  PyYAML gives `int` for an unquoted `1` and `bool(1)` is `True`, so this is the
  check that matters.
- **Suite tallies, run by me from the archive.** `4c33bc7`: 208 tests, 12 failures,
  1 error. `4c33bc7^`: 192 tests, **the same 12 failures and 1 error**. The failures
  are pre-existing (11 `test_scout_script` skips-as-failures needing a live
  agent-script-runner, plus the dashboard import error). Their claim is accurate.

## Finding: the AST guards only see four hardcoded filenames

`chat_sites()` and `test_every_chat_site_body_includes_think` iterate a literal
tuple `("brain.py", "criteria_eval.py", "planner.py", "l3_planner.py")`. The
docstring claims "a new site with no `think` fails it" and the commit message claims
"a 13th call site cannot quietly omit it".

**I tested that claim by adding a fifth-file call site and the guard passed green.**
A function in `agent/agent.py` posting `json={"model": ..., "messages": ...}` to
`/api/chat` — no `think_field()` — left `test_every_chat_site_body_includes_think`
`OK`. `test_every_content_reader_uses_answer_text` has the identical shape and the
identical hole.

Current reach is sound: all five files that mention `api/chat` are accounted for
(`config.py`'s three mentions are docstrings, no call node). So today 12/12 hold.
The gap is that the guard's guarantee is "these four files" while its description,
and the commit message it ships under, say "every call site". That is the exact
failure mode this change exists to prevent — a green test that reads as coverage.

**Fix is small:** derive the file list from the `agent/` tree
(`glob("*.py")` minus tests) instead of naming four, keeping the same AST body.
No change to shipped behaviour.

## Non-blocking observations

1. **"16 new tests" is 11 executed.** The file defines `TruncatedAnswerTests`
   twice (line 152 and line 188), with `if __name__ == "__main__"` sitting between
   them at 184. The second definition shadows the first, so unittest collects
   5 + 6 = 11 of the 16 written; the first class's 5 tests never run. Suite delta
   192 → 208 is therefore 16 by arithmetic but 11 by execution — the 5 shadowed
   tests are near-duplicates of surviving ones, so no coverage is actually lost.
   Worth deleting the dead class and moving the `__main__` block to the end.
2. **`AIBOT_LLM_THINK` is read at import.** Fine for real runs (env is set before
   the process starts). Consequence: `test_default_is_off` fails if the developer
   has the var exported. Consider `mock.patch.dict(os.environ, {}, clear=True)`
   plus an importlib reload in that test.
3. **`LLM_THINK` parsing** uses `.lower() in ("true","1","yes")` — the idiom the
   spec pins. `"on"`/`"y"` are not accepted; consistent with the spec, noted only
   so a future reader does not "fix" it toward truthiness.

## Deploy note

No image build, no rollout. This is the agent-side code; the change is inert until
an image carrying it is built and `AIBOT_LLM_THINK` is set where it is wanted.
