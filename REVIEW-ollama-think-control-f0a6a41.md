# Review — `openspec/changes/ollama-think-control/` at `f0a6a41`

Reviewer: `minecraft-reviewer@minecraft`. Row `qitem-20261113194852-b6c380519c5e72d6`.
Supersedes `REVIEW-ollama-think-control-03ff511.md` (commit `2839d94`).
Read from `git archive f0a6a41` into `/tmp/rev-f0a6a41` — not from a working tree.

## Verdict: NOT PASS — the three findings are closed, one new gap opened by the fix

F1, F2 and F3 are all genuinely closed. What blocks now is different, and it is
caused by the F1 fix: the new eval-runner `think` key has no writer. Detail in N1.

## My two errors, both corrected

**The "15th site" was mine.** I said `output_evals/run.py:54` was a 15th site.
It is the 14th. My grep returned 13 agent-side hits, one of which is the
docstring at `l3_planner.py:10`, leaving 12 real agent sites; +1 for `run.py` =
13, not 14. The builder's arithmetic is right and mine was not. I had noticed
the docstring and then failed to subtract it.

The builder's own count needs a footnote: their 13 is `grep -c` over the four
agent files, which by their `-c` output is 2+1+2+8 = 13, and the 8 includes the
docstring. So their 13 = 12 real + 1 docstring, and their total of 14 is also
12 + 1 docstring + run.py. The docstring inflated both sides by one and they
cancel. The conclusion — 14 sites, `run.py:54` included — is correct.

**The "7 files" was mine.** The gateway tracks 6. I ran `git ls-files | cat -n`
and the last line I read was `grep`'s filename header `(standard input)`, not a
file. Re-checked at `bcef0ca`: six entries, listed, no directories and no
non-blob objects. The builder is right.

Both are the same failure shape: I read a count off output that contained a
non-member, and did not enumerate the members.

## Closed

**F1 — closed.** `proposal.md:62-69` now names all 14 with a per-file breakdown
and names `run.py:54` explicitly. Task `1.5` covers the eval runner, `1.6` tests
it, and the new requirement "The eval runner states its own think value,
independently" cites the packaging reason (`make-evals-configmap.sh`) that
forces a separate key. Task `1.3`'s "fourteen copies" is now "thirteen", which is
right for its own scope (the agent's 13 files-grep hits). The independence
scenario — "changing `AIBOT_LLM_THINK` does not change the runner's request
body" — is a real test, not a restatement.

**F2 — closed.** New requirement section in `proposal.md:53-60` and task `1.7`,
with the scenario "A think-on run is refused before it starts, not after every
case". It correctly ties to `run.py`'s existing "a dead instrument still prints a
verdict" contract rather than inventing a new one.

**F3 — closed.** Task `3.3` now says to stand up the harness as part of this
task, states the six files and that none is a test, and says the `format`
analogy "holds for the code path, not for the test situation". That is exactly
the distinction I raised, in the right place.

## N1 (blocking) — the new `think` key has no writer, and the generator is not in scope

The requirement says the runner's `think` "SHALL come from the eval config
(`evalconfig`)". But the eval config is **generated**:

`evals/make-evals-configmap.sh:70-77` writes `config.yaml` with exactly five
lines — a comment pair, `endpoint`, `model`, `timeout`, `concurrency`. Nothing
else is emitted.

So today, adding `think` to `evalconfig.DEFAULTS` and reading it in `run.py`
gives a key that can only ever hold its default inside the Job. Setting
`MODEL=qwen3.8:27b-q4_K_M think-on` and re-running the generator — which is the
whole point of the run — produces a config with no `think` line, and the run
silently takes the default. The lead would then run the think-on leg and get
think-off numbers, with a report that says `think: false` and looks honest.

Two further specifics, both verifiable at the rev:

- The generator is **not named as an affected file** anywhere. `grep -rn
  "make-evals-configmap" openspec/changes/ollama-think-control/` returns two
  hits, both prose citing it as the *packaging* fact (`proposal.md:73`,
  `spec.md:44`). Neither says it must change. `proposal.md:71` "Affected code"
  lists `agent/config.py`, the 14 sites, and `llm-gateway app/main.py` — the
  generator is absent.
- There is **no scenario for the default**. The requirement and both scenarios
  cover "taken from the eval config" and "refused when the endpoint rejects
  think". Neither states what an omitted `think` key means. Given that F2's
  probe is conditional ("when thinking is enabled", task `1.7`), a missing key
  would leave the probe unarmed *and* the field unsent — the exact failure the
  change exists to prevent, now reachable through a config omission.

**Fix, all inside this change:**

1. Add `evals/make-evals-configmap.sh` to "Affected code" in `proposal.md`, and
   a task line under §1: the generator emits `think:` from an env var (e.g.
   `THINK=${THINK:-false}`) alongside `endpoint`/`model`, so the yardstick
   carries the value in the same place and with the same visibility every other
   yardstick value has.
2. Add `think: False` to `evalconfig.DEFAULTS` and validate it is a real bool —
   the loader already type-checks `endpoint`/`model`/`timeout`/`concurrency`
   (`evalconfig.py:78-87`); a `think` that silently coerces the string `"false"`
   to truthy is a one-character bug that no scenario here would catch.
3. Add a scenario: **WHEN** the eval config omits `think` **THEN** the runner
   sends `think: false`, and the report records that the value came from the
   default rather than the file — matching the precedent `endpoint_from_env`
   already sets at `evalconfig.py:71-77`.
4. Say in task `1.7` whether the probe fires on `think == true` or on `think`
   being set explicitly, so "when thinking is enabled" cannot be read two ways.

This is not scope creep: the requirement as written is unbuildable in a way that
fails silently, and a silent think-off is precisely the bug class the change
was commissioned to remove.

## Unchanged and still correct

Top-level `think` rather than an `options` key; explicit-not-omit; the
`content == "" and done_reason == "length"` predicate; the `("true","1","yes")`
bool idiom; the eleven `message.content` readers all being local edits; the
test/prod split at `proposal.md:28-34`. Nothing in these sections changed
between `03ff511` and `f0a6a41`, and my `03ff511` reasoning on them stands.

## Instruments

- `git archive f0a6a41` → `/tmp/rev-f0a6a41`; `diff -u` against
  `/tmp/rev-03ff511` for all three files, so the review covers the delta and the
  unchanged text is known to be unchanged rather than assumed.
- `openspec validate ollama-think-control --strict` in a **clean archive** at
  `/tmp/scratch-validate` → *"Change 'ollama-think-control' is valid"*, rc 0.
  My first attempt ran it in the qwen worktree, whose HEAD is `2839d94` and has
  no such change; it answered *"Unknown item"*. That is a validator that cannot
  succeed, not evidence either way — the claim is now from a tree that holds the
  rev.
- Site count re-derived at `f0a6a41`: 14 `api/chat` lines under `agent/`,
  including the docstring at `l3_planner.py:10` and `output_evals/run.py:54`;
  13 real agent sites across the four named files.
- `git ls-files | cat -n` in `llm-gateway` at `bcef0ca` → 6 entries.

## Not checked

The gateway has no harness at `bcef0ca`, so nothing under F3 can be run until
the builder's new `3.3` creates one. My F3 closure is that the *task* now
describes the true starting state; it is not a claim that the tests exist.
