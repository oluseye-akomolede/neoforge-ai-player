# Coded agents — LLM-written per-bot scripts

## Why

Today the LLM chooses every step the bot takes. That is expensive, slow
(one round trip per action), and the endurance ladder plateaued partly on LLM
output variance rather than on code bugs.

The design being adopted moves the LLM up to **strategy**: it writes a script
that runs every tick inside the bot, and only rewrites that script when the
situation or the goal changes. The script acts through the bot actions that
already work, so pathfinding, mining and crafting stay in code that is already
tested.

Nothing is built yet. This change is **step 1: the design as an OpenSpec
change** — proposal, tasks and spec deltas — for review before any code.

## Owner decisions (2026-11-10, `qitem-human-answer-181fe641fe26089fc36b`)

1. **Only the LLM writes scripts.** Players do not author scripts.
2. **Players can see the scripts** the system created, in the bot interface.
   Read-only.
3. **Code hours are unlimited for now.** They are a **per-player DAILY cap**
   configured in **mod settings**.
4. **Metering is kept** even though the cap is unlimited by default, so the
   data exists when a cap is turned on.

## Scope

**In scope, this change:** the contract for scripts, sandbox, the read-only
script view, metering and the daily cap, the design of the runner, and the
step-1 tasks that implement the parts that do not depend on an unresolved
question.

**Out of scope:** the production rollout, hive units adopting the system, and
the runner's hosting location (see Open question).

**Open question, blocking one task only:** the runner's hosting depends on
`cardgame-lead`'s answer, because cardgame uses the same JavaScript engine and
the two teams may share a runner deployment. Everything else is specifiable now.

**Open question, blocking an owner decision (tasks 5.2 and 6.2):** the owner's
decisions say the cap is *per player* and that a player sees *their* bot's
script, but **no bot-to-player relation exists in the codebase** — no ownership
field in agent state or `bot-identity`, and the dashboard has no authentication
(no user identity, no token, every route unguarded). So "the owning player" and
"refused because they do not own it" currently name nothing. The owner must
choose: bind bots to a player's Minecraft UUID, bind them to a dashboard user
(which requires building authentication), or treat bots as not player-owned and
specify the cap and script view **per bot**. Metering, sandboxing, the script
contract and the LLM-only authoring rule are unaffected and specified now.

## Design summary

1. **Scripts run outside the game server**, in a separate runner service, so a
   bad script cannot freeze the server. Each bot gets its own sandbox with a
   memory limit and a CPU limit per tick.
2. **Engine:** QuickJS, standard modern JavaScript, shared with cardgame.
   Scripts have **no filesystem and no network access** — the engine is
   configured without those bindings, and escape attempts are tested for.
3. **Per tick**, the script sees a read-only snapshot: the bot's health, food,
   position, inventory, nearby blocks and mobs, task progress and recent events.
4. **Scripts act only through the existing bot actions** — the dispatcher's
   `case` set in `agent/agent.py`: **52 `case` arms** at the time of writing,
   **51** excluding the `_` default, naming **51 distinct actions** (`goto` is
   dispatched twice — a guard arm `case "goto" if "target" in p` plus the plain
   arm). Examples only: `goto`, `mine`, `craft`, `container_extract`. The
   examples are a sample, not the list — `container_insert`, `delegate`,
   `send_item`, `trade`, `shop_buy` and `conjure` are also in the set. What the
   requirement fixes is a **ceiling** (nothing outside that set), not an
   enumeration. The script cannot reach past that surface into the server.
5. **The LLM rewrites the script** every few minutes, or when a new goal
   arrives, rather than choosing each step.
6. **Code hours** are metered per bot; when a bot's allowance runs out the
   script pauses and the bot falls back to keeping itself safe.
7. **The current planner stays** as a fallback.

## Code hours — what the owner chose and what that implies

The owner's answer ("unlimited for now, a per-player daily cap in mod settings")
is a real design constraint, not a deferral, and it shapes the spec:

- **The unit is the player, not the bot.** A player may own several bots; the
  cap is on the player's total script time per day. Metering must therefore be
  attributable to an owning player, per bot, and summed per day.
- **"Unlimited by default" means the cap mechanism must exist and be off**, not
  be absent. A cap added later without metering having run would have no basis,
  so metering is required from the first release.
- **Mod settings** — the existing convention is a JSON file at
  `serverDir/config/aiplayermod-*.json` (as `aiplayermod-shop.json` is), so the
  cap lives in `aiplayermod-scripts.json` alongside the script settings, not in
  a new mechanism.

An earlier draft of the design asked whether code hours should be *earned*
(for example from XP). The owner answered differently: a cap the operator sets,
not a currency players accrue. The XP economy (`bot-xp-economy` spec) is
therefore **not** the mechanism, and nothing here should read as making it one.

## The read-only script view

Players can see scripts "in the bot interface that we created". The existing
dashboard (`agent/dashboard/server.py`, FastAPI, `/api/bots/{name}/…`) is that
interface. The view is:

- **read-only** — no endpoint accepts script text from a player;
- **scoped to the scripts visible to that player** — their own bots;
- **showing the script as it actually runs**, not a stale copy, so what a player
  reads is what the bot executed.

## Risks

- **Sandbox escape.** Mitigated by using a tested engine configured without
  filesystem and network bindings, plus a test set of escape attempts.
- **Load on the game.** A tick-time bound and a per-tick CPU limit, and the
  runner is separate from the server process.
- **Poor scripts from the LLM.** Scripts are validated before they run, and the
  existing planner remains as a fallback.
- **Metering that cannot be trusted.** Metering is measured in the runner where
  the time is actually spent, not inferred in the game server.
