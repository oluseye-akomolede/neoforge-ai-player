# Review — openspec/changes/agent-output-evals at `de7e420` (round 2)

Reviewer: minecraft-reviewer@minecraft. 2026-11-13 ~16:50Z.
Row: `qitem-20261113162928-37115062c5f6665a`.
**Verdict: PASS with one correction.** The corpus is sized from measured data, the
replay design is right, and both of my withdrawn/round-1 points are correctly
handled. One requirement pair is unsatisfiable as written — see Finding 1.

Verified at `de7e420`, worktree clean (0 modified), `openspec validate
agent-output-evals --strict` → *"Change 'agent-output-evals' is valid"*, rc 0.

---

## My withdrawn finding — GONE, and the replacement states the truth

I reported at `61728ce` that the trajectory corpus had no durability guarantee. That
was wrong: I grepped the worktree, found no manifest setting `AIBOT_TRAJECTORY_DIR`,
and concluded from that it was unset on the cluster. The lead measured in the pod: the
variable IS set and the files are on the PVC at
`/opt/aibot-agent/data/agent_trajectories`.

Checked that the false claim is fully gone from the change:

```
grep -rn -i "no durability guarantee|container-local|destroys it|2.0a|make the corpus durable|subPath"
  → no matches (exit 1)
```

What replaced it is correct in both places it now appears: the location comes from
`AIBOT_TRAJECTORY_DIR` (env or the agent's own config), never hardcoded
(`spec.md:32-34`, `INVENTORY.md:113`, `tasks.md:44,60`), and `tasks.md:34` records the
withdrawal with its reason. The false "a restart destroys it, including this morning's
14:53Z rollout" sentence and the proposed follow-on change to make a durable corpus
durable are both deleted. The one surviving note — that the repo never tracks the var
because the live Deployment was patched outside it — is true and is the reason my grep
and the lead's pod read disagreed.

No durability-warning requirement remains in the report spec, so a run will not print a
false warning over a corpus that survives fine.

## Round-1 findings — all three correctly repaired

- **(a) embed miss:** `INVENTORY.md:18-21,69` names `semantic_memory._embed`
  (`:76`, `nomic-embed-text`, `{OLLAMA_URL}/api/embeddings`), lists the five reachable
  call sites (`:90,:139,:247,:274,:396`) matching what I verified, and scopes it out with
  a stated reason rather than omitting it. The inventory no longer implies the local
  endpoint serves only qwen.
- **(b) exec kind set:** the spec scores against the **mod's** `DIRECTIVE_KINDS`
  (`script_client.py:35`) and gives the reason ("a directive the mod accepts is valid
  whether or not the agent's own list names it"). The agent-side gap is named as a
  separate finding, not fixed here, per direction.
- **(c) outcome join:** the inventory now states it per kind honestly —
  `plan | 299 | 0 | plan_ref -> plan_close.status` — instead of implying a per-call
  join that does not exist. The `no_label` bucket and "a case whose label cannot be
  derived MUST NOT be counted as a success" are the right repair.

## The lead's measured facts are encoded correctly

Counts match the row's note exactly: `exec` 1545 calls / 1530 outcomes, `plan` 299,
`replan` 271, `plan_close` 359 (`spec.md:127-129`, `INVENTORY.md:99-101`,
`tasks.md:42-44`). The live model is `qwen3-coder:30b` taken from the bot profile with
the parent row's `qwen3.8:27b` corrected (`proposal.md:11`, `tasks.md:16,44`).

Replay is primary and the historical outcome-attributed score is separate and labelled
weaker — which is the right order, and it means all three kinds are testable from
recorded inputs without depending on an outcome join.

## FINDING 1 (correction) — "prefer today's model" and "30 per kind" are jointly unsatisfiable for `replan`

`spec.md:130-133`:

> The sample MUST be stratified across the bots and across the corpus's model eras, and
> MUST **prefer inputs recorded with the model the agent runs today**.

`spec.md:118-125`:

> The eval set MUST carry at least about 30 cases for each of `plan`, `exec` and
> `replan` **when the recorded corpus holds that many**.

Measured era split (lead's row note, per kind):

| era | exec | plan | replan |
|---|---|---|---|
| qwen2.5:32b-instruct (Aug) | 1395 | 262 | 250 |
| qwen3-coder:30b (Sep+Nov) — **today's model** | 148 | 37 | **21** |

`replan` has **21** records in the preferred era, so at least 30 preferred-era replan
cases cannot be drawn. The two MUSTs pull in opposite directions on the same kind, and
the spec does not say which yields. An implementer will silently pick one — most likely
taking 21 from today's era and 9 from August to reach 30, which is precisely the mixed-era
baseline that the *next* requirement says is not a baseline for today
("a baseline drawn from an older model is not a baseline for today's").

**Suggested fix**, small and in one place: state the precedence explicitly. Prefer the
current era; where a kind cannot reach 30 from it, either (i) accept the current-era
count as the baseline for that kind and report the shortfall in the per-era provenance
line the spec already requires, or (ii) allow older-era cases only to fill to 30 and
require the report to give both the all-era rate *and* the current-era-only rate for
that kind. Either is testable; the current text is not.

This is the same shape I flagged in round 1 — a number promised before the corpus was
counted — now narrowed to one kind, and the counted corpus makes it visible.

---

## What I did not verify

- I did not read the PVC or the pod: `kubectl` is not installed on this VM, and the
  no-exec rule stands. The counts are the lead's measurement, quoted, not re-derived by
  me. Everything above that depends on them is conditional on that measurement being
  right.
- I did not verify the graded per-site verdicts in `INVENTORY.md` for the eight kinds
  outside plan/exec/replan beyond checking the call sites exist and the endpoints match;
  the spec review is about the requirements, and the inventory's per-site "how
  correctness is decided" column is for step 2 to test.

## Bottom line

PASS on design, sourcing, scoring and rerun mechanics; the withdrawn durability finding
is fully gone without leaving a false claim behind. Fix Finding 1's precedence sentence
before step 2, because it decides what number the owner is shown on Friday.

---

## Finding 1 — RESOLVED at `1890221`, by a better argument than mine

The builder first landed `0c0b979` ("current era wins over the 30-case minimum"), then
superseded it with `1890221` ("fill shortfall from August inputs, report per era"). The
second is the correct resolution and I am recording why it beats the fix I proposed.

**Their argument, which I had not weighed:** in a replay eval every *scored output*
comes from the configured model. Only the **input** carries an era. So an August input
is not a stale baseline — it is a fixed prompt re-answered by today's model. My round-2
suggestion treated the older era as a contamination risk and proposed making the
current-era-only rate the baseline; that would have thrown away 250 usable replan
inputs to protect a vintage that does not affect what is being scored.

**What the committed text now requires** (`spec.md:138-147`, `:153-160`):
30 cases per kind, current-era inputs first, any shortfall filled from older inputs;
the per-kind pass rate given **overall and split by input era with the `n` for each**;
and a marked difference between era rates flagged as *possible prompt-format drift,
not model quality*. Each clause is checkable, and `replan`/21 is a concrete instance so
the test has something to bite on.

**Checked the states that matter:** no residual "wins over reaching 30" text survives
(grep exit 1), so the two readings do not sit beside each other; the fill is reachable
(August holds 250 replan against the 9 needed); and the shortfall scenario is scoped to
kinds *short of* 30 in the current era, so `plan` (37) and `exec` (148) are correctly
left current-era-only rather than padded for no reason. `openspec validate --strict`
valid at `1890221`, worktree clean.

The finding stands as filed — the two MUSTs were genuinely unsatisfiable as written —
but the repair is theirs, and it is the better one.
