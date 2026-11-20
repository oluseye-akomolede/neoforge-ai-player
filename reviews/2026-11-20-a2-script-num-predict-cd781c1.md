# Review: a2 SCRIPT call token budget — `cd781c1`

**Rev:** `cd781c1ad0e2fc1c5c177ae18a8ef23349727344` ("a2: give the SCRIPT call room for a whole script")
**Row:** `qitem-20261120191732-936dc02555828d80`
**Prior:** `059c74d` NOT YET on the fence counts (review `e1f1bdf`); the lead said the count fix comes as a
separate commit and this one is diagnostic only. Nothing here depends on the close count.
**Verdict:** **PASS**, with one scenario in the new requirement that no test can fail.

Everything the five checks asked for holds; the numbers below were measured on the deployed model, not
estimated from the source.

---

## The five checks

**(1) `validate --strict`** — `openspec validate ai-written-scripts --strict` → rc=0,
`Change 'ai-written-scripts' is valid`. Run in a clean `git archive cd781c1`; afterwards
`git show cd781c1:…/bot-coded-agents/spec.md` diffed byte-identical against the validated copy, so the file
validated is the rev's file. The delta is ADDED (10 requirements at the rev, the new one last at `:681`),
three scenarios, no behaviour removed.

**(2) Only the SCRIPT call's options change** — every `num_predict` at the rev:

| file:line | call | budget |
|---|---|---|
| `l3_planner.py:491` | PLAN | 1024 |
| `:868` | (400) | 400 |
| `:918` | (24) | 24 |
| `:970` | (200) | 200 |
| `:1006` | (768) | 768 |
| `:1102` | (384) | 384 |
| `:1216` | REFINE-SKILL | 768 |
| `:1412` | **SCRIPT** | `_SCRIPT_NUM_PREDICT` = 4096 |

`brain.py`, `planner.py`, `criteria_eval.py` and `output_evals/evalconfig.py` carry their own values and are
untouched by the diff. The diff is those 8 sites only plus one constant; the remaining options on the SCRIPT
body (`temperature` 0.2, no `format`, `stream` False, `_OLLAMA_TIMEOUT`) are unchanged. I read the body off the
wire from the rev's own `call_script`: keys `['messages','model','options','stream','think']`, `think False`,
`format` absent, `num_predict 4096`, `timeout 420.0`.

**(3) 4096 fits inside the 420 s timeout** — measured against the live `ollama-l3` model
(`qwen3.8:27b-q4_K_M`, `think:false`, the deployment's own settings):

- Cold load is the dominant term: **26.4–68.2 s** (`load_duration`), sometimes over a minute because the
  model reloads after its 24 h keep-alive lapses.
- Generation: **32.05–36.92 tok/s** across a warm and a load-bound call.
- Real SCRIPT body (prompt 676 tokens — 1835-char system prompt with the live 16-skill catalog, plus a
  harvester user turn): 1603 tokens out.
- Worst case: 68.2 s load + 4096/32.05 = 127.8 s generate + ~7 s prefill (4098 tokens measured at 4.3 s)
  = **~203 s against 420 s**, 2.07× headroom. Warm, it is ~130 s.
- A full 4096-token thinking block would be ~80 s at the owner's "thinking costs about double" ratio, which
  still fits.

The limit is not the timeout but the model's **2048-token context**: measured `prompt_eval_count` 676 against
`/api/ps` `context_length` 2048, so prompt + completion shares one window of ~2046. 4096 is therefore generous
rather than tight — the 19:10Z trial truncated at 1024 with a prompt far under 1022. That also means `think`
must stay off: at 676 prompt tokens a thinking reply at this call's size would be cut, not finished. The
deployment leaves `AIBOT_LLM_THINK` unset, and `think_field()` sends `"think": false`; the commit body says so
and the wire body confirms it.

**(4) A length-stopped reply still yields no script** — `call_script` catches `TruncatedAnswer` and returns
`None` (`l3_planner.py:1428-1433`). The consumer is `call_plan:566`, `if script: plan.script = script`, and
`Plan.script` only ever appears through that assignment; `getattr(steps, "script", None)` at `agent.py:909`
and `:1744` treats a missing attribute as no script. So the refusal holds at the rev — and `answer_text`
(`config.py:151-166`) only raises when **`message.thinking` is empty**, which is safe here solely because
`think` is off. This check is not a regression of this change; see G-3.

**(5) One mutant reproduced** — three, each a clean red on a targeted test:

| mutant (what it removes) | result |
|---|---|
| `_SCRIPT_NUM_PREDICT` back to `1024` | `FAIL test_the_script_call_asks_for_more_than_the_plan_budget`, rc=1 |
| `except TruncatedAnswer` re-raises instead of `return None` | `ERROR test_a_truncated_script_call_costs_only_the_script`, rc=1 |
| the SCRIPT branch returns `''` instead of `None` | **`OK` — 47/47 survives** → G-3 |

Suite at the rev from a clean `git archive`: `Ran 47 tests … OK`, rc=0 (44 carried from `059c74d` plus the 3
new ones).

---

## Findings

### G-1 (non-blocking) — the third scenario has no test that can fail it

> "The budget is the script call's own — **a change to the script call's budget MUST NOT change theirs**"

`test_the_budget_change_is_the_script_calls_alone` reads the plan call's 1024 off the wire. That pins the
plan's number; it cannot fail on the scenario's subject, because nothing a change to `_SCRIPT_NUM_PREDICT`
can do moves the plan's literal `1024` at `:491`. The test is the right shape for "the plan call keeps its
budget" and would catch someone copying 4096 in; it does not enforce the independence the sentence describes.
Either reword the scenario to what is testable ("the plan call's budget is 1024 and is not the script
constant") or drop the second bullet. Worth noting for the same reason: the seven other budgets in the table
above are **not** asserted at all — only the plan's is.

### G-2 (informational) — the budget guards a category, and one member of it already exceeds it

A hand-written script in the repo, `agent/scripts/scout.js`, is **14 328 chars** — at this model's measured
ratio (626 prompt tokens / 1890 chars) that is **~4740 tokens**, more than 4096. Planner-authored scripts are
expected to be much smaller, and the trial's script fit in 1024 + 579, so this does not undercut the fix for
today's replies. It is a limit of the requirement as written: "large enough to hold the whole reply it is
asked for" is false for the largest script this project currently ships to the same API.

### G-3 (carried, predates this rev, not caused by it) — a truncated thinking reply can be bound

`answer_text` raises only when `thinking` is empty **and** content is empty. If the model is thinking and runs
out of tokens mid-thinking, content is empty and `done_reason` is `length`, so it raises — fine. But if the
budget ends during the **visible** part after some content exists, `answer_text` returns that partial content
with no error. That partial content is ```` ```js ```` plus part of a script without its closing fence, and
`extract_script_block` finds a block in it: I fed a real 1117-char reply, truncated mid-block with
`done_reason: "length"`, through the rev's own `call_script` and it **returned the script**. With `think` on,
at 4096, a thinking block of ~2500 tokens leaves ~1600 for the script, which is enough (scout.js-scale) to be
truncated with content present. On the deployment `think` is off, so this is unreachable today; it becomes
live the day `AIBOT_LLM_THINK=true`. **Mutant above:** returning `''` instead of `None` survives all 47 tests,
so nothing pins "truncation yields no script" against a future edit either.

---

## What I did not check

- Not built, not deployed, nothing pushed. The lead builds `cd781c1` for test.
- The fence-count NOT YET on `059c74d` stands unchanged; that file's close count is still wrong and it is
  diagnostic-only here.
