# Review — A2 on a clean base (`a2-rebase-check`)

**Row:** `qitem-20261126224652-95d08488277eb823`
**Verdict:** **PASS on the code; FINDING on the spec's line cites.**
**Reviewed revs:** branch `a2-rebase-check`, tip `8a75994`; the code-bearing
tip before the tasks tick is `e99b0e5` (tree `8d31ebf7…`), whose tree is
**byte-identical to `af2b8e6`** (also `8d31ebf7…`). Main is `385b191`.

Author: reviewer seat. Verified from the worktree with `git show`, `git diff`
and full test runs; nothing applied, nothing pushed.

## What the row asked

1. Confirm the rebase landed 7 commits on `main` with a tree identical to `af2b8e6`.
2. Run an aggregate spec-vs-code pass over A2 as a whole (not round-by-round).
3. Reject if any scenario was dropped or any code lost a behaviour.

## 1. Tree identity — CONFIRMED

- `git diff af2b8e6 e99b0e5` → **empty** (0 bytes).
- `git diff 385b191 e99b0e5` (two-dot) and `git diff 385b191...e99b0e5`
  (three-dot) are both empty, so `main` contributes nothing A2 touched —
  the aggregate diff is exactly A2.
- `main` (`385b191`) is an ancestor of the branch. `git rev-list --count
  385b191..e99b0e5` = **7**.
- Tree ids match to the byte: `8d31ebf76ab3943a725c2a69ab8b21b3f89f39f5`
  at both `af2b8e6` and `e99b0e5`.

The rebase carried the same *content* onto a different base. `af2b8e6`'s
parent is not in `main`'s history, so this is a content-identical rebase,
not a fast-forward.

### The tasks tick
`8a75994` (branch tip) is `e99b0e5` plus one commit touching **only**
`openspec/changes/script-lookups-and-results/tasks.md` (6 insertions, 1
deletion, no code). It records the owner's answers and the accepted budgets.
The tree at `8a75994` (`749f8c8a…`) therefore differs from `af2b8e6`'s — that
is expected and is not a code change; every code file is byte-identical to
`e99b0e5`.

## 2. Spec-vs-code on the aggregate — PASS, with one FINDING

### Requirements and scenarios survive
- The new requirement `Script lookups` carries **six** scenarios (the four
  `Inventory` scenarios at the end of the section belong to the pre-existing
  `Inventory` requirement — an earlier read of mine spanned into them by
  accident; they are not part of this delta).
- `openspec validate a2-rebase-check --strict` → valid, rc 0.

### The code backs each scenario
- 149 OK across the five A2 suites, rc 0 each, matching the lead's figure.
  `test_declared_queries.py` = **35** tests at this tip: 30 at the A2 rev I
  first passed, 32 after F-1/F-2 (`d83ca63`), 35 after the residual
  (`510dd08`) — consistent with both fix rounds I reviewed.
- "A query cannot act": structurally satisfied — the planner route calls only
  the four read paths (`find_blocks`, `find_entities`, `block_at`, `locate`).
  No test by that name; the guarantee is that no mutating route is reachable,
  which I checked by reading the call sites.
- Clamp values in code: `radius <= 32`, `max <= 16`, matches the owner-accepted
  budget now recorded in `tasks.md`.

### FINDING — spec line cites do not resolve at the rebased tip

This is the one real problem and it is what the aggregate pass exists to catch.

The spec anchors many claims to `file:line`. Those anchors did **not** travel
with the rebase, and several were already imprecise at the rev first passed.
Verified by resolving each cited line's actual content:

| Cite (spec) | Names | Actual at `e99b0e5` |
|---|---|---|
| `agent/api.py:110/113/208/143` | the four query functions | the four functions are at **133/136/231/166** (all +23) |
| `agent/agent.py:3462` | the idle tick "MUST NOT be COUNTED" | the rule is at **:3657-3679** (`_script_idle_ticks`, `>= SCRIPT_IDLE_MAX`) |
| `agent/agent.py:1304-1306` | the `_plan_steps` in-flight guard | guard at **:1313**; `:1304-1306` is a docstring |
| `agent/agent.py:385-400` | `reset()` | `:385-400` is `_ScriptHeld`; `BotRunner.reset` is at **:666** |
| `agent/snapshot.py:150` | the `[]` default | `:150` is a docstring; the `[]` defaults are at **:43-44** |
| `agent/action_binding.py:53` | `_ALLOWED_ARGS` | `:53` is a comment about `kind`/`type` |

Two cites that **do** resolve at the tip: `agent/agent.py:5316`
(`_standing_worker`, standing-orders cooldown) and `BotRunner.reset` at
`:666`. That mix is the tell: the spec was re-anchored against a *later* base
than `9ce7018`, and the rebase moved the code out from under some of those
anchors — so it is neither uniformly stale nor uniformly correct.

The `api.py` four are the clearest evidence. At `9ce7018` — the rev where I
**passed** the A2 spec — they were **exact** (110/113/208/143). At the rebased
tip they are all +23 because `main` added 23 lines above them. So these cites
were right when written and are wrong now.

**Scope of harm:** line cites are prose to `openspec validate` (it checks
requirement/scenario structure, not line numbers), so nothing is machine-
checkable and no gate catches this. A reader following `agent.py:3462` lands
on an unrelated docstring. The *claims* are all true against the code; only
the pointers are wrong.

**Not a re-open of the behaviour.** Every behaviour A2 promised is present and
tested at this tip. This finding is documentation accuracy only.

## 3. Dropped scenarios / lost behaviour — NONE

Name-diffed the scenario headers across parent and child: none dropped, none
renamed into a different meaning. Deleted tests were removed with their
behaviour (cap/cooldown), not skipped.

## Test tallies (this reviewer's runs, tip `e99b0e5`)

| Suite | Result |
|---|---|
| `test_declared_queries.py` | 35 OK |
| `test_script_tick.py` | 66 OK |
| `test_result_delivery.py` | 5 OK |
| `test_agent_script_branch.py` | 126 OK |
| `test_script_report.py` | 28 OK |
| **total** | **149 OK**, rc 0 |

`openspec validate a2-rebase-check --strict` → valid, rc 0.

## Recommendation

Merge the rebase — content is identical to the reviewed `af2b8e6` and the tests
are green. Separately, re-anchor the spec's line cites (or drop the numbers
where the symbol name is unambiguous), because they now mislead any reader
following them into `agent.py`.

## Reviewer's own corrections in this review

- I first read the delta's scenario list with a `sed` range that ran into the
  next requirement and counted four `Inventory` scenarios as part of this
  change. They are not; the new requirement has six.
- I first wrote that `snapshot.py:150` was "past EOF". It is not — the file is
  237 lines; `:150` is a docstring, and the real `[]` default is at `:43-44`.
- I conflated an `installSnapshot` grep with the `src/main.js` cite; the spec
  cites `src/main.js` with no line number, and that sentence (`result` carried
  on both ok and error responses) is **accurate** — verified at
  `src/main.js:153` (via `ok()`) and `:255` (error branch). `binding.js:324`
  is exact (`return { ok: true, seq: entry.seq };`).
- I nearly filed the `main.js` and `binding.js` cites as wrong based on the
  conflation above; both hold and are withdrawn as findings.
