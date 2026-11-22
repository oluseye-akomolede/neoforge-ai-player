# 1073535 (test-only fix) and image `aeab1dab` — CONFIRMED

Rev: `1073535`. Image: `harbor.arcadia-ecs.local/aiplayermod/agent@sha256:aeab1dab20f85c4953ef660bb4fdf59c6141ad36af947e44a4c8b15d812f2a02`.
Reviewer: minecraft-reviewer@minecraft. 2026-11-22. Closes the one required fix from `0fbc5ac`.

## 1. The diff is expectation-only

`git show 1073535 --stat`: **one file**, `agent/test_script_tick.py`, +11/-3. No production file.

Non-comment additions, verbatim:

```
            {"text": "partial scan, 3 blocks", "truncated": False,
             "ok": False, "error": True},
            "the result a throwing tick carried must be held, as a FAILURE "
            "(`error: True`), not merely as `ok: False` -- a no-verdict "
            "result is read as `done` downstream")
```

Non-comment removals are the same dict without `error: True` and the older message
string. Everything else added is comment. **No code change**, as asked.

### Suites at `1073535`, clean worktree, `nice -n 19`

| suite | result |
|---|---|
| `test_script_tick` | `Ran 62`, `OK`, rc=0 |
| `test_script_client` | `Ran 14`, `OK`, rc=0 |
| `test_script_mode_gate` | `Ran 23`, `OK`, rc=0 |
| `test_l3_script_path` | `Ran 90`, `OK`, rc=0 |
| `test_planner_script_output` | `Ran 19`, `OK`, rc=0 |
| `test_agent_script_branch` | `Ran 141`, `OK`, rc=0 |
| `test_script_prompt_kinds` | `Ran 20`, `OK`, rc=0 |
| `test_scripts_configmap` | `Ran 2`, `OK`, rc=0 |

**431 tests across 8 script suites, all rc=0.** From the previous review, carried
forward and still true: full discover at `1073535` is `Ran 674`, 30 failures, 1
error, 1 skipped — the failure set is **identical by name** to the parent rev
`0eea399~1` (`Ran 666`, same counts). The new failure is gone and nothing entered.

## 2. Image `aeab1dab` carries `1073535`'s production files

Running pod `aibot-agent-test-65b586f795-6ckrx`, image digest matches the one named
(`aeab1dab20f8…`), 1/1 Running, 0 restarts, started 12:44:04Z.

| file in `/opt/aibot-agent/` | pod | rev `1073535` |
|---|---|---|
| `agent.py` | `8bfcf4efe006` | `8bfcf4efe006` |
| `planner.py` | `2c9586a05748` | `2c9586a05748` |
| `script_tick.py` | `9c3baf88ccbb` | `9c3baf88ccbb` |

All three match. Read-only `exec` on test only; nothing in prod touched.

**A caveat on what this proves.** `1073535` changes only a test, and the image ships
no test files (`/opt/aibot-agent/test_script_tick.py` does not exist). So these three
hashes are **identical at `0eea399` and at `1073535`** — I checked both. The
comparison therefore confirms the image's production code is correct, but it cannot
distinguish an image built from `1073535` from one built from the commit before it.
Nothing in the pod labels or annotations names the rev. That is not a defect in the
image; it is a limit on what this check can settle.

**Amendment (lead correction, 13:04Z; verified).** This paragraph originally ended "the
same limit applies to prod's `aea76462`, whose production files are byte-identical to
this one." **That clause was wrong and is withdrawn.** `aea76462` is prod running
`eb5498f`; `aeab1dab` is `1073535`. They are different revs and their files differ:

| file | `eb5498f` (prod `aea76462`) | `1073535` (`aeab1dab`) |
|---|---|---|
| `agent.py` | `793518bbb751` | `8bfcf4efe006` |
| `planner.py` | `2c9586a05748` | `2c9586a05748` |
| `script_tick.py` | `09cdcdfd40c4` | `9c3baf88ccbb` |

The caveat above survives, but on its correct pair: `1073535` sits exactly one commit
after `0eea399`, and `git diff 0eea399 1073535` touches **only** `agent/test_script_tick.py`
(+11/−3). The two revs' production hashes are identical — `agent.py` `8bfcf4efe006`,
`planner.py` `2c9586a05748`, `script_tick.py` `9c3baf88ccbb` at both — so the stated limit
(nothing shipped distinguishes an image built from `1073535` from one built from
`0eea399`) holds. The error was conflating that pair with the prod pair.

## 3. Code-hours cap: no metering exists — noted, not `0eea399`'s

Independently confirmed: **176** Java files under `src/main` (the builder and lead
said 177; my count is 176), zero hits for `3600` / `SECONDS_PER_HOUR` / `MS_PER_HOUR`
/ `code.?hour`. Spec `openspec/changes/coded-agents/specs/bot-coded-agents/spec.md:128`
sets the cap and defaults it unlimited; `:440` requires metering in the first release
even while unlimited. Neither is implemented. **Pre-existing and spec-level**, not
introduced by `0eea399`; it does not affect this verdict and should get its own row.

## Verdict

**CONFIRMED.** `1073535` is a correct, test-only fix; the affected suites are green
and the full suite is back to its parent baseline. Image `aeab1dab` runs production
code matching the rev. Prod is unchanged — prod Mystic's move to this image is the
lead's call after the live test on minecraft-test.

Test-namespace state at review time, for the lead's live test: all five bots log
`script mode on`, and `agent-scripts`'s `bindings.json` is `{"Scout": "scout.js"}` —
**Mystic is unbound**, so the planner must write its script on the first goal. That is
the correct precondition for testing "tell me when it gets dark".
