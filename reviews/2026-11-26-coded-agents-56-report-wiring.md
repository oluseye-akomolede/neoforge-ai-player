# Review: coded-agents 5.6 — wire ReportSender in production

**Row:** `qitem-20261126133335-2ea56bc4`
**Repo:** `neoforge-ai-player`, branch `spec-a2-no-cap-query`, rev `fc61f8477e40` (parent `510dd08`)
**Verdict:** **PASS with one spec-wording nit (F-2).** Reviewed from a clean `git archive` at
`fc61f84`; mutants built and restored by me, byte-identical (`agent.py` md5 `9438096a…`,
`api.py` md5 `b4d969a3…`). Read-only; nothing deployed or pushed.

## The bug was real, and it is proven from the parent rev

`git grep` at `510dd08` (the rev being fixed) over the whole tree finds `script_reporter`
assigned in exactly four places, **all** in `agent/test_script_report.py` (`:299, :328,
:354, :379`). The only production reference is `agent.py:3710`,
`getattr(self, "script_reporter", None)` followed by `if sender is None: return`.

So every live bot booted with no sender and reported `none` — which is what the
2026-11-26 13:30Z deploy showed. The 19 pre-existing tests stayed green because they
attached the sender by hand, and `RunnerSeamTest` builds runners with `__new__`, which
skips `__init__` entirely. That is a faithful account of the defect.

## The fix is correct and minimal

- `agent/api.py:post_script_report` calls `r.raise_for_status()` and does not reuse `_post`.
  Verified against `_post` (`api.py:30`): it is `requests.post(...); return r.json()` with no
  `raise_for_status`, so a 400 carrying a JSON body returns normally. The builder's
  justification is correct, not asserted.
- `agent/agent.py:500` assigns the sender in `BotRunner.__init__` beside `CodeTimeMeter`,
  unconditional and unguarded.
- Spec: new requirement "The Report Channel Is Wired Where The Agent Is Constructed" plus two
  scenarios; task 5.6 carries a correction that quotes the false "wired at the metering seam"
  claim. `openspec validate coded-agents --strict` → valid (rc 0, 1.13.2). The only surviving
  instance of the false claim in the tree is inside the correction that quotes it.

### The builder's three questions

**(a) Can any production path construct a `BotRunner` without the sender?** No.
`BotRunner.__new__` in production appears once, `agent.py:5572`, inside `bound_script_path` —
a lookup-only helper that reads one JSON file, never reports, and is documented as such. The
two real construction sites (`agent.py:5502`, `:6236`) both call `BotRunner(...)` and so run
`__init__`. Every other `__new__` is in a test.

**(b) Is the raise swallowed between `post_script_report` and `dropped`?** No. `raise_for_status`
raises → `ReportSender.report` catches it in `except Exception`, increments `self.dropped`,
returns `False` (`script_report.py:129-133`). `_report_script_state`'s outer `except: pass` is
*behind* that counter and cannot mask it; `_report_observed_at` is a plain `strftime` and does
not raise. Covered by `test_a_raised_post_counts_as_dropped_not_sent`.

**(c) Could the spec requirement be satisfied by a future conditional wiring?** **Partly yes —
this is F-1 below.** The requirement's prose forbids it ("MUST NOT be attached … by an optional
wiring step that a deployment can omit"), so a reviewer reads it as banned. But the tests do not
enforce it.

### F-1 — the tests pin the construction site, not the unconditional-ness (non-blocking here, real)

All three new construction tests go through one helper with one name:

```python
def _constructed(self):
    return self.agent_mod.BotRunner({"name": "Scout"})
```

I built the mutant the requirement is written against — wire it for `Scout`, leave every other
name unwired:

```python
self.script_reporter = ReportSender(api.post_script_report) if self.name == "Scout" else None
```

**Result: 27 tests, `OK`, rc 0.** The mutant survives. The suite cannot distinguish
"unconditional" from "wired for the one bot it happens to construct". The requirement says a
conditional attach "is indistinguishable, from the mod's side, from the feature not existing" —
and the tests reproduce exactly that blindness. On the production path today every bot is
wired, so this is not a defect in `fc61f84`; it is a gap that lets the defect return silently.
Closing it is a test that constructs a differently-named bot and asserts the sender is still
attached, which reddens on the mutant above.

### F-2 — the commit message overstates the mod once

The message (and the code comment's "Verified against the mod") says `ScriptReportStore.record`
"refuses a null `previous_code_hours`". It does not: `record` at `:92-93` tolerates a null and
treats it as absent (`body.has(...) && !…isJsonNull()`). It refuses only a *present, non-null,
non-finite, negative or over-max* value. Harmless in effect — `build_body` omits the field rather
than nulling it (`script_report.py:51`) — but the sentence as written describes behaviour the
mod does not have. Worth a one-line edit so a later reviewer does not trust a wrong fact about
the receiver.

### Answer to "is a correction note the right record?"

Yes, and better than replacing the text silently. The tick remains `[x]` and the note says plainly
that it was ticked while unwired, what the original claim was, and what makes it true now. A
future reader needs the history, not a clean-looking line. The spec requirement is the durable
rule; the task note is the honest record of how it got there. Keep both.

## Tests, run by me

From a clean `git archive fc61f84`, from `agent/`, `nice -n 19`,
`NODE_OPTIONS=--max-old-space-size=2048`:

| suite | result |
|---|---|
| test_script_report | 27 OK |
| test_script_tick | 66 OK |
| test_agent_script_branch | 126 OK |
| test_declared_queries | 35 OK |
| test_result_delivery | 5 OK |
| test_script_say_guard | 8 OK |
| **total** | **267 OK**, all rc 0 |

Matches the builder's 27 / 267.

## Mutants, built by me

| mutant | result |
|---|---|
| M1 remove the wiring entirely | red: 2 failures + 1 error, all three `ProductionWiringTest` |
| M2 condition on the bot name (covers `Scout`) | **green — survives (F-1)** |
| M3 drop `raise_for_status` | red: both `PosterRaisesTest` non-2xx tests |

Both source files restored byte-identical to the archive copies (`cmp` clean, md5s above).

## Out of scope, noted

Code-hour cap (5.4/B2), the A2 query spec, and deploy remain where the row put them. The lead
deploys after the verdict.
