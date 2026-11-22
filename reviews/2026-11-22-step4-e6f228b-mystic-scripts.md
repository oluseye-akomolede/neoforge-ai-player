# Step 4 change e6f228b: Mystic scripts on, empty bindings — PASS with one condition

Rev reviewed: `e6f228b` (builder worktree, redo of rejected `c8dbb27`).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22. Row qitem-20261122120702.
Review only — nothing applied, no pod exec in prod.

## Verdict

PASS on the change. The four questions are answered below; Q4 has a real finding that
does not block step 4 but should be known before Mystic runs unattended.

## Q1 — empty bindings leaves Mystic eligible for planner scripts. CONFIRMED by running the code.

I extracted `script_mode` (`planner.py:271-305`) and `l3_path_enabled` (`:306-346`) from
`eb5498f` and executed them rather than reading them:

    SCRIPT_BOTS=Mystic, runner set:
      Mystic  script_mode=True  l3=True
      Forge   script_mode=False l3=False
      Tiller  script_mode=False l3=False
      Axiom   script_mode=False l3=False
      Scout   script_mode=False l3=False

    Mystic, runner unset   -> (False, 'script mode off: no SCRIPT_RUNNER_URL…')
    Mystic, not in list    -> (False, "script mode off: 'Mystic' is not named in SCRIPT_BOTS")

So `SCRIPT_BOTS=Mystic` alone turns on script mode and the L3 path for Mystic only, and the
other four stay on the legacy planner. Matches the ConfigMap's claims.

I replicated `_bound_script_path` (`agent.py:3957-3986`) against a real `{}` bindings file:
`bindings.get('Mystic')` is `None` → the function returns `None` → the planner path runs. An
empty file is genuinely "planner for every bot", not "no script configured".

And the reason empty is required is real: `_bind_planner_script` checks
`if (self._bound_script_path() or "").strip():` at `:4024` **before** the dry tick and refuses.
A hand-written binding would defeat step 4 rather than support it. c8dbb27 was rightly rejected.

## Q2 — the diff reproduces, and there is nothing in it beyond the claim. CONFIRMED.

`kubectl diff -f` against live, all changed lines enumerated (19 total):

    generation 116 -> 117
    + SCRIPT_BOTS=Mystic
    + SCRIPT_RUNNER_URL=http://agent-script-runner.minecraft.svc.cluster.local:8080
    + SCRIPTS_DIR=/srv/aibot-scripts
    + RUNNER_TOKEN <- secretKeyRef {agent-script-runner-token, minecraft}
    + volumeMount scripts at /srv/aibot-scripts
    + volume scripts <- configMap agent-scripts, defaultMode 420

Nothing else. **The image line is unchanged** (`aea76462…`), so step 4 does not touch the
step-3 image. I checked the three things a diff cannot show:

- Secret `agent-script-runner-token` has exactly one key, `minecraft` (names only; no value read).
- Service `agent-script-runner` serves 8080 (contract) and 8081 (health) — the URL's `:8080`
  is the contract port, not health.
- No secret value appears anywhere in `e6f228b`'s diff.

## Q3 — apply order and rollback are both correct. CONFIRMED, with one sharpening.

Order (ConfigMap first, then Deployment) is **mandatory**, not merely tidy. The manifest's
`configMap` volume does not set `optional: true`, so a Deployment applied first would leave the
new pod in `FailedMount` and, with `strategy: Recreate`, the old pod is already gone — the
whole fleet would be down, including the four bots that have nothing to do with step 4.

Rollback (re-apply the saved Deployment, then delete the ConfigMap) is also correct, and the
order matters for the same reason in reverse. I verified the saved object is safe to re-apply
first: the live Deployment has `volumes: ["agent-data"]`, no reference to `agent-scripts`, and
env `[OMP, MKL, OPENBLAS]` only. Re-applying it removes the mount before the ConfigMap is
deleted, so the pod never references a missing ConfigMap.

One sharpening: the rollback must save the object **immediately before** applying (as the row
says). A save taken now would be the pre-step-4 state, which is right, but a save taken after
the apply would bake in the script env and silently make "rollback" a no-op.

## Q4 — YES. A Mystic script can run with no player's request. This is the finding.

Three sites call `_bind_planner_script`. Two are player-initiated (chat message at `:1221`,
goal orchestrator at `:2138`). **The third is not:**

`agent.py:2275`, inside `_check_task_board()` (`:2229`), which is called from the tick loop at
`:4390` whenever `not self._plan_steps` — i.e. whenever Mystic is **idle**. It claims a task
from the shared Postgres `task_board`, calls `planner.decompose` on the task description, and if
the model returns a `script` it binds and runs it.

Nothing about that requires a player. `TaskBoard.claim` (`taskboard.py:131`) will claim any
`status='pending'` row whose `specialization IS NULL` for **any** bot, and priority-1 rows
posted by another bot's own model. The `delegate` tool (`agent.py:4888`) lets any bot's LLM post
such a row on its own initiative — `created_by=self.name`, no player in the loop.

So the chain is: some bot's model decides to `delegate` → row lands on `task_board` with
`specialization IS NULL` → Mystic idles, claims it, decomposes it, gets a script back → binds
and runs it, with no player having asked for anything.

**Not a blocker for step 4**, and here is why I am not calling it one: it is the owner's
framework working as designed (planner writes scripts for bot-initiated work), the script still
passes `_dry_tick` before binding and `_goal_generation_is_stale` before that, and the runner
still enforces its token. But it is the honest answer to "anything that lets a Mystic script run
without a player's request", and the answer is yes. Two consequences worth stating:

- The "unused by real users" property that step 3 relied on ends here. After step 4, Mystic's
  script path is reachable from bot-initiated work alone.
- If that is not intended, the lever is `specialization`: posting with a non-null specialization
  Mystic lacks makes it unclaimable by Mystic. That is a policy choice, not a defect in this
  change, so I am raising it rather than rejecting on it.

Live state supports "it is not happening yet, but the door is open": prod logs show **0**
`taskboard: Claimed task` lines in the last 70 minutes.

## Not established

- Nothing applied; this is a review of the bytes at `e6f228b` against live.
- I could not read `task_board` contents in prod (the row says no pod exec, and my attempts were
  read-only but did not complete). So "no pending rows right now" is **not** established — only
  that nothing was claimed in the last 70m under the current config, where SCRIPT_BOTS is unset.
- The manifest header says it was generated from live at 12:0xZ; `kubectl diff` agrees with that
  (19 lines, all intended), which is the check that matters.

## Condition on the PASS

Apply ConfigMap first. Re-save the Deployment object immediately before applying, not after.
