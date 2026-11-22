# c0cfb47: withhold the script invitation (N-1 on 2fb40e7)

Rev reviewed: `c0cfb47`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**N-1 is closed.** Both halves of the invitation now follow the surface, and
both are driven rather than read. One finding: a function this commit adds has
no test for the direction it exists to serve.

## What I verified

At `c0cfb47`, all rc read unpiped from a file:

- `test_script_mode_gate`: **18 pass, rc=0**.
- Full agent suite: **Ran 635, errors=1, skipped=1**. The error is
  `ImportError: Failed to import test module: dashboard` (missing uvicorn) —
  the same pre-existing break as every prior rev tonight. *The commit message
  says 637; I ran 635 and report what I ran.*
- `openspec validate coded-agents --strict` **rc=0** (`script-lookups-and-results`).

**Mutants, each red on its own branch, restored `cmp`-identical:**

| Mutant | Removed | Result |
|---|---|---|
| A | `if offered else ""` — section always rendered | 1 red, `test_a_disabled_bot_is_not_taught_wants_script` |
| B | the `if not offered: return plan` refusal | 1 red, `test_a_disabled_bot_that_asks_anyway_costs_no_second_call` |

The commit's account of its *first* mutant surviving is correct and worth
recording, because it is a species I have hit twice myself tonight: the test
rebuilt the prompt from `script_mode` instead of calling production's `.format`,
so mutating production changed nothing the test could see. Extracting
`render_plan_prompt` is the fix, not a convenience — the test now calls
`l3_planner.render_plan_prompt(bot_name)` at `test_script_mode_gate.py:168`,
which is the same renderer `call_plan` calls one frame up at `l3_planner.py:508`.

**Driven, not just read:** a `wants_script: true` reply for a bot outside
`SCRIPT_BOTS` produces exactly one `requests.post` and the plan proceeds on its
steps. The log line names the bot and the reason:

    [Forge] not fetching a script: script mode off: 'Forge' is not named in SCRIPT_BOTS

That satisfies all three spec scenarios, including the "MUST log one line
naming the bot and saying why".

## F-1: `_script_section_from_prompt`'s positive direction is untested

`output_evals/sysprompt.py` adds `_script_section_from_prompt(planner, text)`,
whose entire job is to recover the script section **when the recorded prompt
carried one**. The only test touching it
(`output_evals/tests/test_sysprompt.py:76`) pins the *empty* direction:

    script_section="",

with the comment "the fixture's recorded prompt carries no script section, so
the rebuild recovers """. There is no fixture whose recorded prompt contains the
section.

**Mutant C survives.** Replacing the whole function body with `return ""`:

    Ran 122 tests in 4.871s
    OK

RC=0. The recovery can be deleted entirely and the eval suite stays green.

Why it matters: this is the eval leg that scores recorded planner prompts. If
recovery silently returns `""` for a prompt that *did* carry the section, the
rebuild measures against a prompt the model never saw — which is precisely the
"a plausible substitution is still a lie" property the same file asserts
elsewhere. The disabled case is now pinned; the enabled case, on which the
scripted-goal evals depend, is not.

Suggested shape: a second fixture whose `RECORDED_PLAN_PROMPT` carries
`_PLAN_SCRIPT_SECTION`, asserting the rebuild reproduces it verbatim; and one
where the section text differs (an older rev's wording), which is the case
`_script_section_from_prompt` currently folds silently into `""`. That second
one is a judgement call the builder should make — silently dropping an
unrecognised section may be intended, but nothing states it.

## Not established

No live bot. Whether a real model stops setting `wants_script` when the section
is absent is unobserved, as the commit says. Everything above is the
Python-layer path.
