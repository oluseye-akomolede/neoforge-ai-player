# Review: coded-agents 5.6b — code-hours cap from deployment env (`af2b8e6`)

**Row:** `qitem-20261126140215-0c7d521f`
**Repo:** `neoforge-ai-player`, branch `spec-a2-no-cap-query`, rev `af2b8e6` (parent `07b2a15`)
**Verdict:** **PASS.** All four builder questions answered affirmatively; two non-blocking observations.
Verified from a clean `git archive` at `af2b8e6`; mutants built and restored byte-identical by me.
Read-only — nothing deployed.

## Q1 — All four prior scenarios survive the rewrite (no silent drop)

I diffed the scenario headers by **name** across `07b2a15` and `af2b8e6`, not by count, then read the
bodies. The requirement was renamed `Set In Mod Settings` → `Read From The Deployment Environment`, and
its first paragraph rewritten, but the four pre-existing scenarios are present **word-for-word**:

| scenario | parent | child |
|---|---|---|
| Cap defaults to unlimited | 699 | 727 |
| Each bot has its own allowance | 704 | 752 |
| Exhausted allowance pauses the script safely | 709 | 757 |
| One exhausted bot does not stop another | 715 | 763 |

Four new ones were added alongside (`An unset or empty variable means unlimited`, `A positive number is
the cap`, `An unusable value is reported and falls back to unlimited`, `The cap is read once, not per
tick`). Nothing dropped, nothing weakened. The paragraphs on per-bot accounting, pause-and-keep-safe, and
the per-player out-of-scope rule are carried over unchanged below the new text.

**Observation (editorial, not a defect):** the parent had one scenario `Exhausted allowance pauses the
script safely` with three THEN bullets; the child keeps it but the third new scenario (`An unusable value
is reported…`) is a separate one rather than folded in. That is a split, not a loss — all four bullets
still appear.

## Q2 — The fall-back choice is defensible, and the spec argues it

The row asked for a justified choice between refuse-to-start and fall-back. The spec states the reason
(lines 701-707): `agent/config.py` is imported **before** the health gate runs, so a process that refuses
to start cannot report *why* it failed; every other setting in that module resolves a bad value the same
way (warn, name it, use the default). The one thing the spec forbids is **silence**.

I verified the code matches, not just the prose. All five unusable forms warn loudly on **stderr**, naming
the variable and the offending value, and resolve to unlimited:

```
CODE_HOURS_CAP='abc'  -> "not a number; cap is unlimited"                 cap=None
CODE_HOURS_CAP='nan'  -> "not a positive number of hours; cap is unlimited" cap=None
CODE_HOURS_CAP='inf'  -> same                                              cap=None
CODE_HOURS_CAP='0'    -> same                                              cap=None
CODE_HOURS_CAP='-1'   -> same                                              cap=None
CODE_HOURS_CAP='3.0'  -> (no warning)                                      cap=3.0
```

`isfinite` catches `nan`/`inf` — a plain `float()` + `<= 0` test would have accepted `nan` (all comparisons
false) and let it through as a cap. That detail is right.

The warning reaches stderr, and **stderr is captured by this deployment's log stream** — I confirmed the
pod serves ordinary log lines and that a *clean* boot emits zero `config:` lines (a positive control: the
grep can return hits, there just were none because nothing was misconfigured). So "loud" is genuinely loud
here, not lost.

## Q3 — Resolving in `__init__` does cover every construction path

`CodeTimeMeter.__init__` takes `daily_cap_hours=_UNSET`; when nothing is passed it resolves
`config.code_hours_cap()`. The `_UNSET` sentinel is a distinct object from `UNLIMITED` (`None`), so a caller
that *means* unlimited can pass `None` explicitly and a caller that says nothing inherits the deployment
cap. That is the right distinction.

Every production construction site inherits it:

```
agent/agent.py:493   CodeTimeMeter()      <- no arg, inherits
agent/agent.py:3693  CodeTimeMeter()      <- no arg, inherits  (the lazy fallback)
```

Both are bare calls. The lazy fallback at `:3693` is a *reassignment* of `self.code_time`, not a separate
code path — it constructs through the same `__init__`, so it cannot bypass the resolution. The only other
constructions are in tests, which pass explicit values. So question 3's premise holds: a third path cannot
slip in without an explicit argument, and the test that would catch it (`test_a_meter_built_under_a_cap_env_is_capped`)
builds via the bare constructor.

## Q4 — The behavioural red fails for the right reason

I ran the new test against the **parent's** `code_time.py`/`config.py` with the child's test file:

```
FAIL: test_a_meter_built_under_a_cap_env_is_capped
  self.assertEqual(
AssertionError: None != 3.0 : a meter built while CODE_HOURS_CAP is set must take that cap;
                              returning unlimited means the env var is not read
Ran 1 test in 0.002s · FAILED (failures=1) · rc=1
```

An **AssertionError on the value**, not an `ImportError` or `AttributeError`. `daily_cap_hours()` exists on
both revs (parent `:128`, child `:151`), so the test can reach its assertion — which is exactly what the
builder's docstring claims and what I confirmed independently. The test earns its place.

## Tests I ran myself

From a clean `git archive af2b8e6`, `agent/`, `nice -n 19`, `NODE_OPTIONS=--max-old-space-size=2048`
(no VA cap):

| suite | result |
|---|---|
| test_code_time | 15 OK |
| test_result_delivery | 5 OK |
| test_script_report | 28 OK |
| **total** | **48 OK**, rc 0 |

`openspec validate coded-agents --strict` on the archive: **valid**, rc 0.

My mutants (each built on a copy, restored and `cmp`-verified byte-identical, sha256 `e9c0fbe0…`):

- **M1 — meter ignores config, always unlimited:** reds 2 tests (`FAILED failures=2`). The env-reading
  behaviour is pinned.
- **M2 — collapse explicit `None` into `_UNSET`** (so a caller that means unlimited silently gets the cap):
  reds 2 tests. The sentinel's distinction is pinned.

## Two non-blocking observations

**O1 — `CODE_HOURS_CAP=""` is prohibited by the spec but indistinguishable in code.** The spec says manifests
MUST NOT set an empty value, reasoning that "an explicit empty value and an absent one would then mean the
same thing by two different routes." The parser does exactly that — `raw == ""` returns unlimited silently,
identical to unset. That is *self-consistent* (the prohibition exists precisely because the code collapses
them), but it means the rule is editorial: nothing enforces it, and no manifest in this repo sets the
variable at all (I checked `deploy/agent-deployment.yaml` and `deploy/agent-deployment.prod-step4.yaml`;
neither sets it, and neither does the live `aibot-agent` deployment). So the cap is **unlimited everywhere
today** — the spec's stated "unlimited while testing" state, not a defect. Worth knowing: the feature ships
configured-off, so nothing enforces it until an operator sets the variable.

**O2 — the live deployment never sets `CODE_HOURS_CAP`, so 5.4's enforcement has no cap to enforce.** This is
consistent with the deferred 5.4/B2 scope (enforcement is 5.4's; this change only *reads* the cap), but if
the lead expects the cap to be live after deploy, it will not be — it is unlimited until an operator sets
`CODE_HOURS_CAP` on the agent deployment. Not a 5.6b defect; a deployment-state fact the lead should confirm
is intended.

## Out of scope

Enforcement of the cap (5.4) and deploy remain where the row put them.
