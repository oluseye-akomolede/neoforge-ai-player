# Review: 27c0956 — 1g extended to both edges of the SKILL exemption

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-17
Rev under review: 27c0956 (branch ship-ca27-harness)
Obligation: qitem-20261117110822-f2724600be15fffe

## Verdict

**PASS.** The residual suffix finding from my `d1f13dd` review is closed, and
the exemption is now pinned against all three weak forms it could plausibly be
written as. Test-only, one file, orchestrator unchanged.

## What I verified (clean `git archive 27c0956`)

### The three mutants, reproduced independently

Anchors `plan_orchestrator.py:626` (directive side) and `:632` (flag side), each
asserted unique (count==1) before every write, restored `cmp`-identical after:

| mutant | failures | all inside 1g? |
|---|---|---|
| `startswith("SKILL")` | 10 | yes |
| `endswith("SKILL")` | 10 | yes |
| `"SKILL" in kind` | 20 | yes |

Baseline at the committed rev: **61 PASS, 0 FAIL, rc=0**. Matches the builder's
counts exactly (10 / 10 / 20).

The suffix mutant is the one that motivated this commit, and it now reddens on
`XSKILL` — the exact check that was green before.

### The test now discriminates equality from every weak rule

The four near-miss names cover both edges: `SKILL_X` and `SKILLETY` (left edge,
including one that a `startswith("SKILL_")` rule would let through) and `XSKILL`
and `EVIL_SKILL` (right edge). No single-sided match satisfies all four. The
docstring says this and the fixture implements it — the wording and the fixture
now agree, which they did not at `d1f13dd`.

### Suites

- `test_dispatch_must_start.py`: **61 PASS, 0 FAIL**, rc=0
- `test_action_binding.py`: **15 tests, OK**, rc=0
- `tests/test_planner_prompts.py`: **8 tests, OK**, rc=0
- `openspec validate dispatch-must-start --strict`: **valid**, rc=0 (rev printed
  as 27c0956 in the same command)

### The history event

The builder amended `d1f13dd` and swallowed my review commit `f89f2db`, then
reset back. I checked rather than took the account:

- `git reflog` shows the amend (`ef3516e`) and the reset to `f89f2db`
- `REVIEW-d1f13dd.md` is present and **byte-identical (3977 bytes)** at both
  `f89f2db` and `27c0956`
- `git diff f89f2db..27c0956` touches only `agent/test_dispatch_must_start.py`

Nothing of mine was lost, and the remedy was correct. My review files carry the
same risk as any other unpushed commit on this branch, which is worth stating
plainly: they live only in this worktree until the lead merges.

### db0d913 (follow-up, no verdict of its own)

Docs-only: tasks.md 2.3 note plus 3.3 tick. I read the note. It retracts the
builder's earlier "qcode produced no patch" against their own interest — the job
returned a valid 27+/35- patch at 71s and they had stopped waiting. The stated
reason for not applying it (it asserted two of the three properties) is the
right reason. 3.3 is ticked citing `d1f13dd` PASS at `f89f2db` with `27c0956`
named as awaiting its own verdict rather than folded in — correctly scoped.

## Instrument errors of mine (recorded so they are not mistaken for findings)

- Grepped `^PASS` for a tally and got 0 on a suite that prints `  PASS`
  (two leading spaces). The zero was my pattern, not the suite. Recounted by
  matching the indented form.
- Ran the first mutant sweep with `python3 -I`, which drops the script's
  directory from `sys.path`; that produced rc=0 with no checks at all. Re-ran
  without `-I`.
- Printed `--stat` and then re-sent a path to the same `git show` and read the
  commit message twice, briefly mistaking it for the file diff.

None reached the verdict. All three are the same family: a zero or a silent
stream read as a property of the world.

## Notes

- The exemption itself is untouched at `27c0956` — `git diff f89f2db..27c0956`
  is the test file only. I re-confirmed the exempted kinds still dispatch and
  the four near-misses do not.
- qcode's rejected patch is not evidence about the committed test; the
  committed test stands on its own measurements above.
- Nothing pushed, merged or deployed from this seat. 3.4 (image build, TEST roll,
  live check) remains the lead's.
