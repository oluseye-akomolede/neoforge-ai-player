# Review — M2-PLAN §8.4 run plan, commit 534458c

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Row: `qitem-20261113100843-1b24fe6e9c67c4c9`
Plan only. Nothing executed, nothing run against the cluster.
Verdict: **findings — not ready to run.** One blocker (C2), three corrections,
one confirmation.

---

## BLOCKER — §8.4.4/§8.4.5 cut EVERY bot, which §8.3 forbids in as many words

The plan patches `SCRIPT_RUNNER_URL` on the **agent Deployment** to reach C2a
and C2b. That variable is process-wide, and the Deployment runs `replicas: 1`,
so the cut reaches all five bots, not Scout alone.

That is not my inference — §8.3 states it, twice:
- `:894-895`: "an implementer reading 'agent-side, on Scout alone' against a
  single-replica Deployment with process-wide env will reach for the env var,
  and the result would be a proof that passes while secretly cutting off every
  bot."
- `:918`: "the proof on TEST uses whichever the run plan can configure
  **without touching the shared Deployment**."

§8.4.4 does exactly the thing those two sentences rule out. Measured in the
code, not inferred:
- `config.py:18` reads `SCRIPT_RUNNER_URL` from the process env at import.
- `script_tick.py:194` does `from config import SCRIPT_RUNNER_URL` inside
  `_default_transport()`, and `:287` uses that transport for **every** bot.
- There is **no per-bot transport in production code**. `ScriptTick` accepts an
  injected `post` (`:246`), but that is a test seam; nothing binds a per-bot URL
  at runtime.
- No per-bot alternative exists today either: no profile has a `script` key
  (checked all five: axiom/forge/mystic/scout/tiller) and no code reads one.

So the two "one-bot" mechanisms §8.3 describes (`:899` closed port, `:902`
accept-and-never-reply) are, as written, only reachable through the shared env.
The section's constraint and its recipe contradict each other.

**Why it matters beyond tidiness:** C2's whole point is to isolate one bot's
runner failure. Cutting all five proves the fallback fires, but it also
perturbs four bots that have nothing to do with this control, and the plan's
own void conditions do not detect it — they check Scout's line, not the others'
behaviour. A run that passes would have "secretly cut off every bot".

**Options for the lead (I am not choosing):**
1. Add the per-bot runner URL the plan already assumed exists (profile key or
   `scripts/` entry), then run C2 per-bot as written. This is a code change and
   therefore needs its own review — it is not a plan edit.
2. Run C2 as a whole-pod cut, and say so in the plan: it is a *system-level*
   fallback proof, not a Scout-only control, and four bots fall back for the
   duration. Acceptable if the lead wants the branch proven and the fleet
   perturbation is acceptable on TEST.
3. Drop C2 from this plan and keep the negative control at unit level (§4.4).

I did not find a fourth option in the code, but I may be missing one the
builder knows about — see question 4 below.

---

## CORRECTION 1 — C1's evidence and C1's configuration contradict (§8.4.1, §8.4.6)

The builder asked this directly (question 3) and the instinct is right that
these are different branches — but the plan currently states them as if they
were one.

- **Absent file** (`FileNotFoundError`, `agent.py:2767-2771`) prints
  `[Scout/script] no bindings at …; this bot runs the planner`. That is a
  **line**.
- **Present map without Scout** (`bindings.get(self.name)` falsy,
  `agent.py:2779-2781`) returns `None` **silently, with no line at all**.

§8.4.6 step 4 expects "no `[Scout/script]` action line for Scout at all" while
step 2 configures the **absent-file** case. Absent-file produces a line, so
"no line at all" is the wrong expectation for that configuration.

And the plan already knows the hazard: `:1287-1290` records that gating on a
bare `Scout/script` count broke on exactly this resolver line, and says gate on
`dispatch:`/`not executed:` instead. §8.4.6 step 5 does that correctly. But
§8.4.1's table cell and §8.4.6 step 4 both drift back to "no `[Scout/script]`
line at all".

**Fix:** pick one branch and state its own evidence.
- Keep **absent-file** (my recommendation: it is the deployment-fault case
  §8.3 already established, and its line is a positive marker): evidence is the
  `no bindings at` line present **and** zero `dispatch:` lines.
- Or use **present-map-without-Scout** and then "no line at all" is literally
  true — but it tests a different branch (silent skip, not deployment fault),
  and the run would then be measuring a bot that was never bound rather than a
  deployment with bindings removed.

Do not leave the cell claiming one branch's line while the step configures the
other.

---

## CORRECTION 2 — the restart claim is right, but `bound_script_path()` is not the check for it (question 2)

I looked for invalidation paths and found none that a restart is avoidable
through, so the claim holds:
- `_script_loaded` is set true once (`agent.py:2806`) and reset **only** in
  `__init__` (`:206`).
- The drone adoption worker (`:3795-3810`) rebuilds `BotRunner`, but only for
  names matching `DRONE_RE` (`Drone\d+`/`Officer\d+`, `:3769`). Scout does not
  match, so its runner is never rebuilt that way.
- The fleet re-spawn at `:3842` calls `api.spawn(n)` — it restores the *entity*,
  not the `BotRunner`, so the cache stays.

But: `bound_script_path()` (`:3850`) is a module-level door that builds an
`__new__` instance and calls `_bound_script_path()` **fresh**. It answers "what
would a new process bind," **not** "what is the live bot running." If any step
uses its output as evidence that a control arm has taken effect *without* the
restart, it will read the new config while the running bot still serves the old
cached script — the false pass §8.4.2 exists to prevent.

§8.3's use of it (`:1179`) is a **precondition before** the restart, which is
correct. I found no §8.4 step misusing it. So this is a caution to keep, not a
defect to fix: never let `bound_script_path()` stand in for the restart.

---

## CONFIRMATION — the arm-distinguishing lines are correct (question 1)

Measured with `requests` against both shapes, not inferred from the constants:
- closed port `127.0.0.1:1` → `ConnectionError` → `fallback_connect_refused`,
  detail `connect refused:` (`script_client.py:169`).
- listener that accepts and never replies → `ReadTimeout` → `fallback_timeout`,
  detail `read timeout:` (`:167`); a slow connect gives `ConnectTimeout` →
  `fallback_timeout`, detail `connect timeout:` (`:166`).

`api._post` (`api.py:33-35`) wraps `requests.post` with no retry and no
re-raise, so the types reach `call_runner` unchanged. The two states are
genuinely distinct and both are required, exactly as §8.4.1 says.

One sharpening: the plan's C2a void condition ("void if the state is
`fallback_timeout`") is right in intent, but note `ConnectTimeout` also maps to
`fallback_timeout`. A closed port should never produce it, so seeing it there
means something other than a refusal happened — voiding is correct. Worth
saying explicitly that the *detail prefix* (`connect refused:` vs
`connect timeout:`/`read timeout:`) is what distinguishes them, since the
state alone does not carry the reason you are citing.

**And a trap for C2b (question 4, related):** an **unset/empty**
`SCRIPT_RUNNER_URL` does **not** produce a fallback state. It returns
`no SCRIPT_RUNNER_URL configured` (`script_tick.py:32-33`, `:295-299`) — a
different code path that never calls `call_runner`. C2b must set a URL that
points at the listener; leaving it empty would look like a control and prove
nothing about the bounded wait. C2b as written sets a listener URL, so it is
correct — this is worth stating as a void condition so a future run does not
"simplify" it to unsetting the var.

## CONFIRMATION — Q4's reading is correct

Patching the **Deployment's** env and pointing it at a listener does not touch
the runner service. The runner is a separate Deployment with its own image and
`replicas:1`; nothing in this plan stops, restarts, or reconfigures it. The
shared-runner constraint is respected by the *mechanism*. (The problem in the
blocker is not that it touches the runner — it does not — but that it touches
all five **agents**.)

## CONFIRMATION — the controls do not depend on the undeployed trap fix

The builder's claim checks out. `call_runner` cuts at the transport
(`script_client.py:160-172`): connect/read timeouts and connection errors are
raised by `requests` **before** any runner response exists, so no runner-side
classification is involved. `aa7b00a` changes how the runner classifies an
error *it* produced; the controls never get a response from it. §8.4.8's
"known limit" is correctly scoped.

## On the three lead points

(a) **Naming the no-regression check correctly.** The plan should not claim
this rollout *tests the fix*. §8.4.8's acceptance is about the arms' contrast,
but the lead is right that the *rollout* acceptance is 4/5: ticks stop erroring.
That is a no-regression check, not a proof. The proof is the reviewed suite
(127/127 + mutation, `c347051`). I agree with the lead's framing and recommend
§8.4.8 or the rollout step say it in those words.

(b) **Shared-runner survival + flat restart count.** Not in §8.4. Any rollout of
`342c10e1` restarts the shared runner, so "cardgame's sessions survive or are
re-established" and "restart count / child respawns flat for 10 min" belong in
the rollout steps, not the control plan. They are missing; add them.

(c) **Rollback digest re-read.** §8.4.9 covers agent-side rollback (saved env,
saved bindings, restart, re-read both). It does **not** cover the runner
rollback — that is the separate rollout row. Fine as scoped, but a reader
following only §8.4.9 could think rollback is complete. One line saying "the
runner's own rollback lives in the rollout row" would close it.

## Bottom line

The plan's method is sound and better than what it replaces: per-arm
distinguishing lines, void conditions, and the §8.3.1a lesson applied. The
blocker is real and is a scope question only the lead can settle — it is
whether a whole-pod cut is acceptable, or whether the per-bot mechanism gets
built first. Corrections 1 and 2 are wording/precision, cheap to fix.

Not OK'd to run as written. Nothing executed.
