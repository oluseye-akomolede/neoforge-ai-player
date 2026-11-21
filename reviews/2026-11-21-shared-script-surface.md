# Review — `a4451a3` + `c27b2e4`: one shared script surface for both prompts

Rev: `a4451a3` (code+tests) and `c27b2e4` (spec+tasks) on `88bcb12`,
branch `ship-ca27-harness`. Row 58ee29a7.
Requested by minecraft-builder@minecraft 2026-11-21 19:30Z.
Reviewer: minecraft-reviewer@minecraft.

## Verdict

**FAIL — one blocking defect (F-1), plus F-2.** The gap it closes is real and
the extraction is the right idea, but the extraction broke the brace escaping
on **both** prompts. The model now reads doubled braces as literal text.

The builder's headline claim — "drift between the two texts is now impossible
by construction" — is true of the *words* and false of the *rendering*. The
tests cannot see this because they render through the same broken path.

## F-1 (blocking) — the shared constant reaches both prompts with `{{ }}` unescaped

`SCRIPT_SURFACE` was written to live *inside* a `.format()` template, so its
literal braces are doubled (`{{ok, seq}}`) — `.format` collapses them. After the
extraction the same doubled string is consumed two ways:

1. **Legacy** (`planner.py:216`): `PLANNER_PROMPT.format(..., script_section=SCRIPT_SURFACE)`
   — the value is substituted *after* `.format` parses the template, so the
   doubled braces are **not** collapsed.
2. **L3** (`call_script`, `:~1624`): `_SCRIPT_SYSTEM_PROMPT.format(..., script_surface=_SCRIPT_SURFACE)`
   — same, substituted as a value, not collapsed.

Measured by rendering exactly those two call sites:

| rev | legacy prompt artefacts | what the model reads |
|---|---|---|
| `88bcb12` (before) | **0** | `Returns {ok, seq} or a rejection.` |
| `a4451a3` (after) | **7** | `Returns {{ok, seq}} or a rejection.` |
| `c27b2e4` (after) | **7** | same |

Seven artefacts in each of the two prompts: `{{ok, seq}}`, `{{ok: true}}`,
`{{ok: true, kind: 'blocks', matches: [...]}}`, `{{ok: true, kind: 'entities',
matches: [...]}}`, `{{ok: true, ageMs}}`, `{{ok: false, reason, message}}`,
`{{id, block, position}}`.

This is a **regression introduced by this commit**, not a pre-existing defect:
at `88bcb12` the script section was inline in `PLANNER_PROMPT`, so `.format`
collapsed the braces and the legacy prompt was clean. Extraction turned an
escape that was correct in place into an escape that is wrong at both new call
sites.

### It violates the spec scenario this change adds

`c27b2e4` adds to `bot-coded-agents/spec.md`:

> #### Scenario: The L3 script prompt carries the same surface
> - **GIVEN** the L3 script prompt rendered for a goal, as `call_script` renders it
> - … **AND** dropping either prompt's copy of the surface, or letting the two
>   diverge, MUST fail this scenario

The requirement is stated on the **rendered** text (as the neighbouring scenario
"The rendered prompt names every call, with its shape" also is), and the
surface as rendered carries seven `{{…}}` sequences. The scenario's own
divergence bullet is also unmet: a test that renders through the same broken
path cannot detect divergence, which is exactly the F-1 blind spot.

So F-1 is not a style nit against new prose — the code fails a scenario the
same commit introduced.

### Why the tests miss it

`test_l3_script_path.py:1457` renders via
`_SCRIPT_SYSTEM_PROMPT.format(..., script_surface=_SCRIPT_SURFACE)` — byte for
byte the production bug. A test that renders through the defect cannot observe
it. No assertion in either test file looks for `{{`. The comment at
`test_planner_script_output.py:97` even says "the section uses doubled braces"
— true of the source, no longer true of what the model receives.

### Root cause, and why the obvious fix is wrong

The two consumers need **opposite** escaping. Unescaping `SCRIPT_SURFACE` to
`{ok, seq}` and re-running: **9 errors, `KeyError: '"steps"'`** — the legacy
`PLANNER_PROMPT.format` now tries to interpret every brace in the surface as a
format field. So the fix is not "drop the doubling"; it is to make the two call
sites agree:

- **Preferred:** stop routing the surface through `.format`. Give
  `PLANNER_PROMPT` the same treatment as `_SCRIPT_SYSTEM_PROMPT` uses — a
  placeholder replaced by concatenation or `.replace()` after formatting — so
  the constant can hold plain single braces.
- **Or:** keep the doubling and pass the surface through a `.format()` pass of
  its own, i.e. `SCRIPT_SURFACE.format()` at both sites, then insert.

Either way, add an assertion that the **rendered** prompt contains no `{{` and
no `}}` — that is the gate this change was missing.

## F-2 — the charged/free sentence in the L3 prompt is correct, but unverified by rendering

The rendered L3 sentence reads

> `api.do`, `api.say`, `api.send`, `api.remember`, `api.log` and `api.result`
> each count; `api.recall()` and ...

which matches `binding.js` (six `accept()` sites at `:342/:359/:372/:413/:434/:474`;
`recall` returns `state.memoryIn` with no accept; `look` is `GUEST_SOURCE`).
So the content is right — the defect is only the brace form. Noting it so the
fix does not get read as "the new text is wrong".

## What is correct

- The gap is real: `_SCRIPT_SYSTEM_PROMPT` said "this is the whole surface" and
  named only the six original calls, so `look` and `api.result` were invisible
  on the live path (`USE_L3_PLAN_LAYER` on). Worth closing.
- Removing *"Return an array of actions (or [] to do nothing this tick)"* is
  right. `worker.js:150` does `const { value: _discarded, ...wire } = result;`
  — confirmed at the runner rev: the top-level return value is dropped at the
  one place a tick result is formed, with a comment saying so. The old line
  told the model to report through a channel that discards it. The replacement
  text is accurate and points at `api.result`.
- `l3_planner` genuinely imports the constant (`from planner import
  SCRIPT_SURFACE as _SCRIPT_SURFACE`) and passes it at the real call site;
  there is no second copy of the text.
- The builder's M2 account is honest and the tightened assertion is the right
  shape.

## Suites

- `test_planner_script_output` + `test_l3_script_path` + `test_agent_script_branch`:
  **Ran 173 tests, OK**, rc=0.
- `openspec validate script-lookups-and-results --strict`: valid, rc=0.
- Full discovery: **Ran 458 tests, FAILED (errors=1)** — the single error is
  `dashboard`, `ModuleNotFoundError: No module named 'uvicorn'`, the known
  environment breakage. Matches the builder's figure.
  (One caveat on my own method: I briefly saw a second `FAIL` in
  `test_scout_script` because I had two discovery runs overlapping, and that
  test writes and deletes a shared `__scout_driver__.mjs` in the runner root.
  Run alone: **27 OK**. It is a latent fragility in that test's scratch
  filename, present before this change and not caused by it — but worth knowing
  if suites are ever run in parallel.)
- All mutants run with `python3 -B` (my pyc lesson from `4eee5fb`); worktree
  restored and verified byte-identical (`cmp`) after each.

No `ollama-l3` requests, no pod exec, nothing in `ci`.
