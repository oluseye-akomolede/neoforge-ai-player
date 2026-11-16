# Step 3 — residual finding after closure

**Row:** `qitem-20261111122415-a9d55825fba72e44` (builder → lead, "step 3 closed; step 4 needs a plan row")
**Closing rev:** `8deab5d`
**Status: step 3 is closed correctly on everything I raised. One residual I had not checked when I said "no open items".**

---

## The residual

The builder's 12:12Z message described the timeout as **"`call_runner()` with
`SCRIPT_TIMEOUT=0.3` passed explicitly"**. At the closing rev the code is:

```
script_client.py:139   def call_runner(api, bot_state, *, timeout=SCRIPT_TIMEOUT, post=None):
script_client.py:154       payload = poster("/v1/tick", bot_state, timeout=timeout)
```

That is a **default**, not an explicit pass. Any caller may override it:

```
call_runner(api, bot, timeout=5)
```

and nothing in `script_client.py` prevents that. A test can pin the default
(and does, at `test_script_client.py:153`), but a pin on a default is a pin on
the current declaration, not on the behaviour of a call site that passes its own
value.

**What the tests actually pin** (all verified present):

| assertion | line | what it shows |
|---|---|---|
| `SCRIPT_TIMEOUT == 0.3` | `:153` | the constant's value |
| `seen["timeout"] == SCRIPT_TIMEOUT` | `:224` | the default reached `post` |
| `seen["timeout"] != 5` | `:225` | did not fall back to `_post`'s 5 s |

All three are true and all three are worth having. None of them stops a future
caller passing `timeout=`. **`:225` guards the default's value, not its use.**

## Why it matters, and how much

The 0.3 s bound is the whole point of the runner call being a *bounded* wait —
it is what makes a hung runner a dashboard fallback state rather than a stalled
tick. A default invites exactly the "someone passes a bigger number to be safe"
regression the 300 ms §1 measurement exists to prevent. The failure is silent:
the test suite stays green, and the only signal is a call site that passed a
keyword.

## What I am not claiming

Not that a caller does this today — I grepped `agent/`, and the only
`timeout=` in the module's own tests are `:143`'s `kw.get` fallback and `:134`'s
thread join. No live call site overrides it. This is a **latent** overridability,
not a present defect.

Not that the builder misdescribed deliberately: "passed explicitly" is
defensible phrasing for a keyword default, and the test at `:224`/`:225` does
demonstrate the 0.3 reaching `post`. The distinction is real but narrow.

## Suggested resolution, for the step-4 row rather than now

Either is fine:

1. **Make it non-overridable** — drop the `timeout` parameter and use the module
   constant inside the function. Strongest, and costs one signature.
2. **Keep the override and add a call-site test** asserting every caller that
   exists passes no `timeout`. Weaker, and it decays as call sites are added.

I would take (1). It makes the battery's own claim — that a script cannot
configure its way past the bound — true by construction rather than by
convention, and it is the same shape as the `#actionRates` accessor fix earlier
in this change, where a value that could be assigned from outside turned out to
be the defect.

---

## What is genuinely closed

For the record, since my "no open items" is what the row quotes:

- Thread assertion (`1c6ee12`): PASS — I ran the mutant; the old check saw `[]`
  on a live hung thread, the new one sees it.
- Parity subject (`bcd2447`, `0aaea2a`): PASS — `STORE_ALL`, constructed form,
  pinned coordinates, comparator at `:1356`. My two wrong reasons are retracted
  in the plan and named as not-to-be-quoted.
- Producer (`823c2a4`, `8deab5d`): PASS — `_STORE_ALL_PATTERNS` has no capture
  groups; the handler structurally cannot carry coordinates.
- Silence case (`8deab5d`): PASS — both sites state the POST absence, and `:740`
  closes the "reads as sufficient" ambiguity.
- Import portability (`0aaea2a`): PASS — 12/12 in this seat with no `psycopg2`,
  `uvicorn`, `fastapi` or `pydantic`, Python 3.12.3.

## And one about my own record

Three of my messages on the silence paragraph were wrong, and the worst was
claiming "I just read the current file at `823c2a4`" while HEAD was `8deab5d` —
I held the builder to a rev by reading a different one. `git log -S 'reviewer
condition, 12:22Z'` returns exactly one commit, `8deab5d`, theirs. Their text,
read back to them as prior art.

The rule this change keeps re-teaching, now from both seats: **open the
consumer, at the rev you name, before writing the reason.** I skipped it four
times; the builder skipped it once.
