# Gate — M2 plan at 771a2ef

Rev: `771a2ef`, branch `minecraft-wt-deepseek`, `openspec/changes/coded-agents/M2-PLAN.md` (272 lines)
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS with three corrections and answers to §11's three questions.**
Plan-only; no code, no spec delta, no cluster change.

## First, my error

I first reported `771a2ef` absent from the repository. It was not — I searched
`/home/sigmastrain/minecraft/agent-script-runner`, and the plan is in
`neoforge-ai-player`. The builder's message named `agent-script-runner` earlier in
the row and `neoforge-ai-player` in the resend; I took the first and never
re-checked when the second arrived. "Absent from every ref" was a true statement
about the wrong repository. The scoped-absence discipline failed on the
*repository* axis, which is the axis I did not print.

## Citations verified

All eight line cites land exactly at `771a2ef`:

`agent/agent.py:152` `class BotRunner` · `:2584` `def _loop` ·
`agent/api.py:33` `_post` · `:43` `get_directive` · `:98` `status` ·
`:101` `inventory` · `:104` `entities` · `:107` `blocks` · `:428` `set_directive`.

## Correction 1 (blocking for §2's proof): the set is 36, uppercase — not 51

§2 says `api.do` names "one of the existing 51 directives (`agent/agent.py`
dispatch)". Two problems:

- **The count is 36**, at `agent/l3_planner.py:204` `_VALID_DIRECTIVE_KINDS`
  (a frozenset of 36 names, `MINE`…`UNFUSE_BLOCK`). There is no 51 anywhere in
  `l3_planner.py`. If 51 came from counting something else, say what.
- **They are uppercase**, and dispatch upper-cases: `agent.py:904`
  `kind = str(directive.get("kind","")).upper()`, likewise
  `l3_planner.py:159`, `:227`, `:267`. §2's example is
  `api.do("NOT_A_REAL_-DIRECTIVE")`, and §6's script "says once". A script
  written with lowercase names (`"mine"`, `"say"`) will *pass* case-insensitive
  resolution — fine — but the refusal test must also prove a **valid** directive
  in either case is accepted, or it only proves the invalid path.

Consequence for the proof: `set_directive` (`api.py:428`) does **no** validation —
it builds `{"type": directive_type}` and POSTs. So the refusal §2 promises has to
be built in the new `agent/script_client.py`, not inherited. §2 currently reads as
if the check already exists somewhere. It does not. State that the check is new
work and name the set it reads.

## Correction 2: §1's latency measurement must compare against the right budget

§1 says four calls "at ~250 ms tick cadence" and that >150 ms "consumes the tick
budget (250 ms)". But `TICK_DELAY = 2.0` (`agent/config.py:27`) is **0.5 ticks/s**
— a tick is 2 s, not 250 ms. The 250 ms is the runner's `deadline_ms`, a
different quantity. One snapshot costing 150 ms leaves 1850 ms of the 2 s tick;
it does not consume a budget. The measurement is still the right first step, but
it is being compared against the wrong number in the plan that decides whether to
add a mod endpoint. Restate: four calls against a 2 s cadence and against the
100 ms bound §4 sets for the runner call.

This is the third time this specific pair has been confused in this change
(`deadline_ms` 250 vs tick cadence), so the plan should say which is which once,
explicitly.

## Correction 3: §4's 100 ms bound and `_post`'s existing 5 s default

§4 sets connect+read at 100 ms. `api._post` defaults to `timeout=5` and is used
throughout. The new client must not reuse `_post` with its default, and a test
should pin that: a 5 s default on the script path would stall a tick five times
over. Worth one line in §7's file table so the reviewer of the code knows the
distinction was deliberate.

## Answers to §11

**1. Measure before adding the endpoint — agree, and go further.** Do not add
`GET /bot/{name}/snapshot` to the mod in M2 at all. A new mod endpoint is a Java
change, a rebuild, and — per §7 — the plan currently promises the mod is *not*
touched. If the measurement says four calls are too slow, the cheaper fix is
caching in the agent (the four calls are all already made by the planner, so a
short-TTL cache in `api.py` is agent-only). Escalate to a mod endpoint only if
the cache also fails, and then as its own reviewed change.

**2. `say` for parity — accept, and the reasoning is right.** `say` isolates the
binding from world state, which is the claim under test. `MINE` deferred is
correct. One addition: record the **counter-case** too — a script that calls
`api.say` when the planner would *not* have said anything. Parity proves the
paths agree when both act; it does not prove the script can act when the planner
would not, which is the point of the milestone.

**3. ConfigMap now, not later — deferring is the expensive choice.** The plan
already argues that script storage is 6.x's read path, so the storage decision is
load-bearing beyond M2. A ConfigMap is not more work than a baked file for one
script, and it removes "changing a script needs an image rebuild" from the M2
proof: §8 requires stop/restart of the runner as a negative control, and if the
script is baked in, changing it and re-proving requires a rebuild mid-proof. Use
a ConfigMap mounted at `agent/scripts/`, keep the `{revision: sha256}` sidecar as
planned. If you prefer baked for M2 speed, say so with the rebuild cost named —
but do not leave it implicit.

## What is right, and worth keeping

- **§0's decision (agent calls the runner, not the mod)** is the correct one and
  the argument is the contract's own: §7 exists to keep execution out of the game
  process. The plan shows the agent already speaks HTTP to the mod, so this adds
  no new capability to a new process.
- **§8's three-part evidence with a negative control** is the strongest part of
  the plan. "Not the bot moved" is exactly the defect this milestone could ship,
  and requiring runner-side seq *and* agent-side apply *and* game-side effect
  rules out each single-point false pass. The stop-the-runner control makes
  "it works" testable against the failure it must survive.
- **§4.4's accept-and-never-reply listener** is the right test shape — a closed
  port proves nothing, and the plan says so.
- **§9's rollback** correctly notes the runner is independent and M2 degrades to
  the previous behaviour rather than to none.

## Non-blocking note

§2's proof test asserts the runner returns an unvalidated name as an action.
That is true of the runner, but the test lives in the agent's suite and proves
the *combination*. Fine — just name it so, since a reader will look for the
runner-side refusal that deliberately does not exist.
