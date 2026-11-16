# Review — bb1d445 (branch ship-ca27-harness)

**Verdict: PASS.** Closes my `fee4e53` NOT PASS (`9be33a9`).

Reviewed at `/tmp/mc.bb.joU8W8`, a clean `git archive bb1d445`. No cluster
actions; every test bounded with `timeout(1)`.

## What the lead asked

| # | Question | Answer |
|---|---|---|
| 1 | delta claims only what ca27b6e's prompt does | **yes** — verified line by line, below |
| 2 | each kept scenario rests on a real prompt line | **yes** — 12 plan + 3 replan fragments, all resolve |
| 3 | `openspec validate --strict` | **valid** |
| 4 | `l3_planner.py` + planner tests identical to ca27b6e | **identical**, by sha256 |
| 5 | tests on a clean archive, bounded | 122 evals OK, 8 planner OK, gate rc=0 |

## 1–2. Every quoted fragment resolves in the shipped prompt

Checked by importing `l3_planner` from the archive and normalising whitespace,
so a quote that only matches across a line wrap still passes (and a quote that
is genuinely absent still fails). Plan prompt 5712 bytes, replan 743.

Plan prompt — all present:
- "If any part of the task names something this server does not have, or asks
  for two mutually exclusive things at once, you MUST decline"
- "a plausible substitution is still a lie"
- `"fly to the moon" → refuse: there is no moon`
- "Do NOT convert these into a nearby achievable goal"
- "Naming the real goal is the whole point"
- `"kind": "clarify"` / "too vague to act on" / "go get some stuff" /
  "make it better" / "ask what exactly is wanted, naming the ambiguity" /
  "which stuff, and how much"

Replan prompt — all present:
- "Output ONLY a single replacement subtask JSON (no prose, no fences)"
- "You MUST return that one subtask object. There is no error form: …"
- "Change the approach — different tool, different route, smaller first step,
  explicit prerequisites — until it can plausibly succeed."

The prompt context around "too vague" reads correctly in full, so the clarify
scenario is describing what the prompt actually says, not a paraphrase.

## The absence direction (what failed at fee4e53)

The rework's vocabulary is gone from **both** the delta and the prompt:
`transient`, `precondition`, `missing capability`, `gathers them`,
`world fact`, `world property`, `bot inventory`, `held tool` — 8 terms, 0 hits
anywhere. That is the precise defect of `fee4e53` and it is now closed: the
delta no longer describes rules the shipped prompt does not contain.

## 4. Identity with ca27b6e

```
l3_planner.py            797739220453a5445070de06524a28bd20b47c220c8219eb774cf9c193f4c14a
test_planner_prompts.py  942d2ca977c061d247271484086f1858c0a17439d4e5ffa9a86a2a0e868fec2f
```
Both hashes match the same blobs at `ca27b6e`. `git diff --stat ca27b6e bb1d445
-- agent/ evals/` confirms no code change: the only files are the harness
commit's own, untouched by this one.

## 5. Tests (clean archive, `nice -n 19`, bounded)

- `agent/output_evals` — **Ran 122 tests, OK**
- `agent/tests/test_planner_prompts.py` — **Ran 8 tests, OK**
- `evals/check_apply_matches_job.py` — **rc=0**

Two instrument notes, since both produced plausible-looking output first:
- `openspec validate --strict` with no item validates **nothing**. Validated
  by name instead: `Change 'planner-prompt-declines' is valid`.

  **Correction (16 10:2xZ).** An earlier version of this file said that bare
  form "prints help text and exits 0". That is wrong, and the error was mine,
  not the tool's: I had the command piped through `tail`, and in a pipeline the
  shell reports `tail`'s status, not `openspec`'s. Re-run without the pipe on
  this rev (openspec 1.13.2), bare `--strict` prints 184 bytes to **stderr**,
  0 to stdout, and `rc=1`. Every rc quoted below was taken with
  `${PIPESTATUS[0]}` or without a pipe.

  A related claim that `openspec validate --check` exits 0 on an unknown
  option was withdrawn by its author after the same defect was found: they had
  measured it through a pipe to `head`. Re-measured without one, `--check`
  prints `error: unknown option '--check'` (32 bytes, stderr) and exits
  **1**. No exit-0-on-error path is known on this install, and nothing in this
  review rests on the existence of one.
- `python3 -m unittest discover -s agent/tests` fails with
  `Start directory is not importable` — `agent/tests/` has no `__init__.py`.
  Ran the file directly with `PYTHONPATH=agent`, which is the correct shape.

Repo-wide, for the merge: `openspec validate --all --strict` is
**23 passed, 7 failed (30 items), rc=1**. The seven are `store-all-ae2-bettercombat`,
`v11-rl-planner-tuning`, `v4-bot-vault`, `v5-locate-recon`, `v6-tempad-waypoints`,
`v7-player-in-the-network`, `v8-inventory-menu-directives` — all "No deltas
found", all pre-existing. `planner-prompt-declines` is **not** among them; it
passes. A repo-wide validate is therefore not clean on this branch, and that is
not caused by this change.

## Commits on ca27b6e..ship-ca27-harness for the merge

**Review/checkpoint `.md` only — keep off main:**
`defe51a`, `5c3af72`, `c454587`, `2df6ebc`, `9be33a9`, `852fb02`

**Content:**
- `fee4e53` — the eval harness. **Note:** it also carries three review files
  (`REVIEW-139def80.md`, `REVIEW-93583d6.md`, `REVIEW-ceaf23a.md`). They ride
  with the first harness commit rather than sitting in their own; if the lead
  wants a clean main history, those three need to be stripped or the commit
  split. Flagged, not a blocker.
- `bb1d445` — the delta fix, this review.

## Not covered here

The still-unowned pin: `evals/job-evals.yaml` pins `a9e75ad1` while the test
deployment runs `2914fb85`. A green eval Job is evidence about a different
image until that is reconciled. Unchanged by this commit.
