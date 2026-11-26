# Review: host-api-count-seven, the change itself (`def85dd`)

**Verdict: PASS.** The lead asked for a judgment on the change rather than only the
cites, against three named criteria. All three hold at `def85dd`, with one correction
to the framing of criterion 1 (below). Nothing blocks archive.

- Repo: `neoforge-ai-player`, branch `spec-host-api-seven`
- Reviewed rev: `def85dd` (base `c920f6a`)
- Row: `qitem-20261126230757-652cf726b66aac34`
- Prior reviews: `315f12e`, `cec433d`, `de009e5`, `dbf2fea`, `f457c42`, `61df265`, `4cae197`

## What `def85dd` adds over what I last reviewed

One commit, `4cae197..def85dd`: `check_cites: say the sort key and the threshold test are
one comparison` — my L-1 note. Script only. All substantive assertions below are therefore
about `4cae197`'s content, re-derived at `def85dd` rather than carried forward.

## Criterion 2 — nothing in `openspec/specs/` may move ✅

Strongest form available: every path in `git diff --name-status c920f6a def85dd` is an
**addition** (`A`), and all four are inside `openspec/changes/host-api-count-seven/`:

```
A openspec/changes/host-api-count-seven/check_cites.py
A openspec/changes/host-api-count-seven/proposal.md
A openspec/changes/host-api-count-seven/specs/bot-coded-agents/spec.md
A openspec/changes/host-api-count-seven/tasks.md
```

Zero modified files, zero deletions, nothing outside the change dir. The live spec is not
edited — not "edited consistently", not edited at all.

The delta also carries exactly one header, `## MODIFIED Requirements`, with no `ADDED` and
no `REMOVED`. So the change's scope is 4 of the live spec's 25 requirements, modified in
place; it does not introduce or delete a requirement.

## Criterion 3 — the delta quotes each requirement's live text ✅

All four delta requirement names are present verbatim in the live spec. Scenario coverage,
computed per requirement as ordered lists at `def85dd`:

| Requirement | delta | live | names identical & ordered |
|---|---|---|---|
| The Planner MAY Author A Script As The Plan For A Goal | 3 | 3 | yes |
| A Written Script MUST Pass A Dry Tick Before It Is Bound | 8 | 8 | yes |
| The Script Prompt Names The Host API The Sandbox Binds | 2 | 2 | yes |
| A Planner-Written Script's Source Is Logged When It Binds | 3 | 3 | yes |

16 delta, 16 live, no drop, no renamed scenario. Nothing live was removed without a delta
saying so.

## Criterion 1 — "change only the count/list" ⚠️ true in meaning, not literally

The lead's phrasing under-describes the diff, and it matters for the archive record, so
stating it plainly rather than agreeing.

- The **count/list** changes are exactly right: `six`→`seven` at R1 (×2), R2 (`log` is one of
  the seven), R4 (`seven host calls`); and R3's enumerated set gains `result` and moves from
  `remember, log` to `result, remember, log`. Zero occurrences of `six` remain anywhere in the
  delta; four of `seven`, one per requirement.
- But R2 also moves **twelve cite positions** and R3 rewrites its cites and adds a
  provenance sentence. None of that is count-or-list.

I have reviewed that work across four rounds and it is correct — but "only the count/list
changed" is not accurate, and a reader checking the archive against this description would
be misled about how large the delta is. The honest formulation: **the only change to
normative meaning is the count/list; the rest is re-anchoring citations to the runner rev
the prose was verified at, with no change to what any requirement requires.**

## Cites re-verified at `b48c4ad` (not carried forward)

Every cited line in R2 read directly at `b48c4ad`:

| Cite | Line reads | Sentence's claim |
|---|---|---|
| `binding.js:96` | `export const MAX_ACTIONS_PER_MIN = {...}` | the 8-action cap's source |
| `binding.js:111-118` | `createBotState()` returning `logTimes` + `actionTimes` | both live on one object |
| `binding.js:192-195` | `createApi(state, { actionRates = ... })` | `createApi` takes `botState` |
| `binding.js:214-216` | `acceptAction(kind)` → `botState.actionTimes[kind]` | always rejects or pushes |
| `binding.js:342-346` | `accept() ?? acceptAction("do")` | `do` pushes onto a local array |
| `binding.js:436` | `state.memoryOut = blob` | the per-tick write |
| `binding.js:459-466` | `botState.logTimes` window | `log` spends `logTimes` |
| `engine.js:254` / `:851-853` | creation / `#installApi` passing `botState` | creates it / passes it each tick |
| `fleet.js:166` | `let worker = this.#workers.get(botId);` | `#ensure` reuses the worker |

All nine hold. One I checked specifically because it looked like a duplicate: `111-118` is
cited both for `actionTimes` surviving a tick and for "the same `createBotState` object". It
is correctly one range — `createBotState` returns both `logTimes` and `actionTimes`, so the
two sentences name two different fields of the same object and cite the same object's extent.

## Validate

Run in a scratch worktree detached at `def85dd` (rev printed, worktree removed after):

- `openspec validate host-api-count-seven --strict` → valid, **rc=0**
- `openspec validate bot-coded-agents --strict` → **rc=0**, INFOs only (long requirement
  text, pre-existing), no change-to-live leak

## Summary

Change itself: PASS. Live spec provably untouched (all additions, none outside the change
dir); scope unchanged (4 of 25 requirements, one MODIFIED header, no ADDED/REMOVED); all
four requirements' live text and scenarios reproduced verbatim. The one thing to fix is the
description, not the code: the delta does more than change the count and list — it re-anchors
citations — and the archive note should say so. `check_cites.py` remains a manual aid, not a
gate.
