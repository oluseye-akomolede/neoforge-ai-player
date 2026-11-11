# Review — M2 step 4 (iii), range `f17fc10..ef8680b`

**Row:** `qitem-20261111133655-a8f208d2a3b3d069`
**Verdict: PASS on the code and the range. Three conditions before the next run.
One number in the builder's report is wrong; the substance behind it is right.**

Reviewed at `ef8680b` in a clean `git archive` export. `Ran 82 tests, OK` over
six modules (`test_script_tick`, `test_agent_script_branch`, `test_script_client`,
`test_scripts_configmap`, `test_action_binding`, `test_snapshot`).

Nothing deployed. No secret value printed; the token appears only as
`test-token-not-real` in the tests.

---

## 1. The three questions the builder asked, answered by running them

### Q1 — does the gate-anchored test read the gate? **YES, and it generalises.**

`_RUNNER_SERVER` now points at `src/server.js`, the file that validates.
The test scrapes `body\??\.(\w+)` and requires the tick body to carry each hit.
Run against the real runner at `e5595e0`, the regex returns
`['contract_version', 'game_id']` — both genuine pre-routing gates
(`server.js:152`, `:158`).

Four mutants, all mine:

| mutant | result |
|---|---|
| drop `contract_version` from the body | **3 failures** |
| drop `game_id` from the body | **2 failures** |
| point `_RUNNER_SERVER` at a file with no gates | **1 failure** (empty-set guard) |
| add an `unsigned_field` gate to the runner source | **1 failure** |

The fourth is the one that matters and the one nobody claimed: a gate added to
the runner tomorrow, with no matching body field, fails this test without anyone
editing it. That is what "anchored on the gate" has to mean to be worth the name,
and this test now does it. The failure mode they described — `handleTick`
destructuring, which only runs *after* acceptance — is structurally gone.

### Q2 — can `_bound_script_path` silently fall back? **YES. This is a finding.**

`agent.py:2682`:

```python
scripts_dir = _os.getenv("SCRIPTS_DIR") or _os.path.join(
    _os.path.dirname(__file__), "scripts")
```

`agent/scripts/bindings.json` is **baked into the image** with
`{"Scout": "scout.js"}`. Verified in the export:

```
SCRIPTS_DIR unset              -> /…/agent/scripts/scout.js   (exists: True)
SCRIPTS_DIR set, no ConfigMap  -> None
```

So when the ConfigMap mount is missing but `SCRIPTS_DIR` is also unset, Scout is
bound from the image's own copy — a working script with the wrong file, which is
exactly the failure they asked me to check for. It is not silent in the *log*
(the path is reachable), but nothing distinguishes "bound from the ConfigMap" from
"bound from the image" at the point of use.

The `FileNotFoundError` branch comments call this "quiet by design" for a bot
with no script. That is right for a bot *absent from the map*; it is not the same
as the map itself being absent while a baked-in copy exists.

**Not a blocker for this range** — the plan sets `SCRIPTS_DIR` in step 2 before
any binding exists, so the deployed path is the ConfigMap. **Condition 1** below.

### Q3 — is token-unset distinct from unreachable? **YES.**

```
url set, token unset -> _default_transport(): None
  tick() -> (False, [], [], 'no runner token configured (RUNNER_TOKEN unset); …')
no_runner_detail() != no_token_detail(): True
```

The token-unset path returns `None` from the transport and never POSTs, so it
cannot be confused with a connection failure. A *real* 401 from the runner is a
different path again — `requests.HTTPError` from `raise_for_status` lands in the
generic `except Exception` and becomes `STATE_FALLBACK_ERROR`, distinct from
`REFUSED` and `TIMEOUT`. Three distinguishable reasons, as asked.

No path prints the token value. `git grep RUNNER_TOKEN` returns only the config
read, the two detail strings, and the tests.

---

## 2. One reported number is wrong

The handoff says the bind-every-bot mutant "now fails 2 tests". I ran it:

```
bindings.get(self.name) or "scout.js"
Ran 15 tests — FAILED (failures=1)
FAIL: test_an_unbound_bot_gets_no_script
```

**One test, not two**, and `1` across the full six-module suite as well. The
guard is real and it catches the mutant — the defect they describe (a mutant
binding every bot passing the whole suite) is genuinely fixed. The count is
wrong, and it is the second time in this exchange a test tally has drifted from
the artefact. It matters less than the substance and I would not hold on it; I
note it because the number will be quoted.

I also cannot reproduce "55 tests green": the six modules are 82. Not a
contradiction — 55 is a narrower selection — but the two figures should not both
circulate as "the suite".

---

## 3. Conditions before the next TEST run

**C1 — the baked-in `bindings.json` must not be reachable in the deployed image.**
Either remove `agent/scripts/bindings.json` from the image, or make
`_bound_script_path` refuse the `dirname(__file__)` fallback and log loudly when
`SCRIPTS_DIR` is unset. Today the safe-looking default (env unset) is the unsafe
one on a pod where the mount failed. One test should assert it: `SCRIPTS_DIR`
unset **and** a baked-in map present must not bind.

**C2 — the unauthorized deploy needs a line in the plan, not only in the row.**
`d42f1268` was deployed to TEST without the ordered review. It is rolled back to
`9de2a68`, and the builder has said run 2 is diagnostic. That is the right state.
What is missing is a note in §8.3 that says the run happened, what it produced,
and that it is not milestone evidence — otherwise the next reader finds a run in
the cluster history with no explanation.

**C3 — the two runs are not comparable.** Run 2 failed at the contract gate on
every tick, so the agent fell back to the planner and *the control and the real
run were the same code path*. Any row in §8.3.5 that reads a difference between
them is reading run 1's numbers or nothing. The plan should say the baseline is
run 1, or that run 2 establishes nothing about the script path.

---

## 4. What I did not verify

- Nothing cluster-side. I did not read the deployment, the ConfigMap, or the
  rollback state; the builder's account of `9de2a68` is taken as reported.
- The runner's own behaviour at request time — I read `server.js` as source, not
  a live 401 or 409.
- The other four bots under the new binding scheme. `_bound_script_path` returns
  `None` for a bot absent from the map, and `_get_script_tick` then returns
  `None`, so the loop falls through — read from source, not exercised on a pod.
- `gen-scripts-cm.py` regeneration equivalence: the drift test passes, which
  compares the ConfigMap to `agent/scripts/`, and that is the consumer's check.

---

## Summary

| item | verdict |
|---|---|
| Q1 gate-anchored test | **PASS** — reads the real gate; new-gate mutant fails it |
| Q2 `_bound_script_path` fallback | **FINDING** — baked-in map binds Scout when env unset |
| Q3 token vs unreachable | **PASS** — three distinct reasons, no token printed |
| `contract_version` in tick body | **PASS** — value is `1`, pinned separately |
| builder's "fails 2 tests" | **WRONG** — it is 1; guard is real |
| suite "55 green" | not reproducible — 82 over six modules |
| unauthorized deploy / rollback | correct state, **needs a plan note** (C2) |
| run 2 as evidence | **none** — control and run took the same path (C3) |

The code in this range is a real improvement over the version I reviewed at
`bf94724`: the contract gate would have turned away every tick, and the tests
that should have caught it were reading the wrong side of the boundary. They
caught it themselves, named the cause precisely, and fixed the class rather than
the instance. The conditions above are about the *next* run, not this code.
