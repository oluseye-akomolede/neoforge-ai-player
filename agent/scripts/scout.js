// scout.js — the M2 first script (task 8.2). One bot, one action.
//
// Written against the runner's real surface (agent-script-runner
// src/engine.js): a frozen global `snapshot`, and `api.do`, `api.say`,
// `api.send`, `api.remember`, `api.recall`, `api.log`. The script runs once
// per tick in a disposable sandbox, so it keeps no state between ticks except
// through `api.remember` / `api.recall`.
//
// M2 scope is deliberately one action. The point of 8.2 is not that the bot
// does something clever: it is that the SAME action reaches the mod whether a
// script or the LLM asked for it. A narrow script keeps the comparison honest.

var GOAL = "scout_store";

function tick() {
  // No snapshot means the agent sent none. Doing anything here would be acting
  // on a guess, so say so once and propose nothing.
  if (typeof snapshot === "undefined" || snapshot === null) {
    api.log("scout: no snapshot this tick, proposing nothing");
    return;  // propose nothing: the runner reads api.do, not this value
  }

  // The envelope's shape is {tick, server_ms, state, events, task}; the bot
  // facts live under `state`, not at the top. Reading `snapshot.health` here
  // gave undefined, so `typeof health === "number"` short-circuited and this
  // guard NEVER FIRED - a bot at health 3 still proposed an action. Every test
  // missed it because the fixtures fed the flat object the script wanted
  // rather than the envelope the cache produces; the guard is now tested
  // against an envelope built through SnapshotCache.
  var state = (snapshot.state || {});

  // Only act once we are actually healthy enough to move. A starved or hurt
  // bot acting on a stale plan is how a bot walks into lava while it is
  // already fleeing something.
  var health = state.health;
  if (typeof health === "number" && health < 8) {
    api.log("scout: health " + health + " too low, holding");
    return;  // propose nothing: the runner reads api.do, not this value
  }

  // STORE_ALL must not fire on every idle tick.
  //
  // WHAT: STORE_ALL is a bank-everything directive. Firing it unconditionally
  // on every tick means a bot that is already unloaded pays for a full store
  // pass every tick, forever, and the mod queues a directive per tick.
  //
  // WHY THE OBVIOUS GUARD IS WRONG: `state.inventory` is NOT a list. The
  // endpoint returns `Map.of("inventory", bot.getCachedInventory())`
  // (HttpApiServer.java:469) and the agent stores that body verbatim
  // (api.py:101), so the shape is
  //   state.inventory = { inventory: [ {slot, item, count, display_name} ] }
  // Reading `state.inventory.length` on that object yields `undefined`, so a
  // `length > 0` guard NEVER FIRES - the same silent-never-fire class as the
  // health guard above (which read the flat shape and so never ran). The list
  // is `state.inventory.inventory`.
  //
  // WHEN: only when there is something to store, and not again for the same
  // inventory for a while. The cooldown is stored as the tick number it was
  // last fired at, compared against the current tick, rather than a countdown:
  // `api.recall()` returns the blob this tick STARTED with, so a value
  // decremented and remembered in the same tick is not visible until the next
  // one (agent-script-runner engine.js:398-406). A tick-number stamp needs no
  // decrement and cannot drift if ticks are skipped.
  var STORE_ALL_COOLDOWN_TICKS = 100;
  var inv = (state.inventory && state.inventory.inventory) || [];
  if (!Array.isArray(inv) || inv.length === 0) {
    // This guard runs before the task check, so this line fires both for a bot
    // carrying nothing and for one mid-store that already deposited everything.
    // Say which, because these log lines are evidence in the C1/C4 arms and the
    // second case must not read as the guard misfiring.
    api.log("scout: inventory empty, not storing (" +
            ((snapshot.task && snapshot.task.progress &&
              snapshot.task.progress.phase === "idle") ? "idle" : "already deposited") + ")");
    return;  // propose nothing: the runner reads api.do, not this value
  }
  var now = (typeof snapshot.tick === "number") ? snapshot.tick : 0;
  // `api.recall()` returns the decoded STRING the game sent, and `remember`
  // takes a single string blob (contract §4.1). So the memory is JSON text on
  // the wire and must be parsed here; reading a property off the raw string
  // yields undefined and the cooldown never engages.
  var mem = {};
  try {
    mem = JSON.parse(api.recall() || "{}") || {};
  } catch (e) {
    mem = {};  // a corrupt blob must not wedge the bot: store rather than stall
  }
  var lastStore = (typeof mem.lastStoreAllTick === "number") ? mem.lastStoreAllTick : null;
  if (lastStore !== null && now - lastStore < STORE_ALL_COOLDOWN_TICKS) {
    api.log("scout: stored at tick " + lastStore + ", cooling down");
    return;  // propose nothing: the runner reads api.do, not this value
  }

  // The task we are on. `snapshot.task` is the directive the agent is
  // currently running, so a script does not start a second job underneath one
  // already in flight.
  //
  // It is NOT null when idle. Measured on TEST 2026-11-12, api.get_directive
  // returns, at rest:
  //   {"state":"Standing by","self_preservation":"ok","progress":{"phase":"idle"}}
  // and, mid-task:
  //   {"state":"Wide search ...","directive":{"id":7,"status":"ACTIVE",...},
  //    "progress":{"phase":"pathing_to_cell","recent_events":[...]}}
  // So `if (snapshot.task)` was ALWAYS true and this script never acted: an
  // idle bot looked busy. The discriminator is progress.phase === "idle", not
  // the presence of the object. The fixtures in test_scout_script.py are copied
  // from those two real responses, not constructed from what this script
  // expects -- a hand-built idle `null` would have confirmed the wrong guard,
  // which is exactly how the snapshot.state bug at line 30 survived every test.
  // Hold unless the task is PROVABLY idle. "Busy" is everything else,
  // including a directive that carries no progress block at all -- an older
  // mod, a shape we have not seen, or a bare test directive. Writing this as
  // `phase !== "idle" && progress exists` would let a directive we cannot read
  // through as idle, which is the unsafe direction: the script would start a
  // second job underneath an unknown one. Only an explicit idle phase opens it.
  var task = snapshot.task;
  if (task && !(task.progress && task.progress.phase === "idle")) {
    return;  // propose nothing: the runner reads api.do, not this value
  }

  // THE ACTION. This is the one 8.2 compares, and TWO things about it matter.
  //
  // HOW: it goes through `api.do`, NOT a returned array. The runner collects
  // actions only from api.do calls during the tick (agent-script-runner
  // src/worker.js:86 `actions: state.actions ?? []`), and its contract is
  // explicit that a script's return value is IGNORED (src/engine.js, §4.4).
  // This script used to `return [{kind:"STORE_ALL"}]` from tick() and end with
  // a bare `tick();`: the value went nowhere, state.actions stayed empty on
  // every tick, and the mod was never asked to do anything. Measured on TEST
  // 2026-11-13 against the live runner - the committed bytes gave
  // {"status":"ok","actions":[]} while a probe identical except for calling
  // api.do gave actions:[{directive:"STORE_ALL"}]. The test that should have
  // caught it REWROTE this file's `tick();` into `;return tick();` before
  // evaluating, so it asserted on a contract the runner does not implement.
  //
  // WHAT: `STORE_ALL` takes an OPTIONAL coordinate triple
  // (StoreAllBehavior.java:62 `if (directive.hasLocation())`), and when it has
  // one it stores into that specific container and moves the bot there (:171).
  // Leaving the coordinates off asks the mod to choose, which is the form the
  // planner's own seed match produces (agent.py:1888 -- its pattern has no
  // capture groups).
  //
  // This script emits the COORDLESS form on purpose, and 8.2 pins that form.
  // Every producer in this repo emits it coordless: the planner's own seed
  // match (agent.py:1888) returns a bare object because its pattern has no
  // capture groups, and the mod's seed specs put the coordinates on AREA_LOOT
  // with STORE_ALL bare beside it (SkillRegistry.java:154). The coordless form
  // is therefore the plausible call, and a constructed fixture should
  // construct that one.
  api.do("STORE_ALL", {});
  // Stamp the tick we fired at, so the next tick can cool down. One string
  // blob per the contract: preserve keys we do not own, since the memory is
  // shared with the planner's own usage.
  mem.lastStoreAllTick = now;
  api.remember(JSON.stringify(mem));
}

// Called explicitly so a syntax error surfaces as a script failure rather than
// as an empty action list. The call is the contract: whatever tick() does to
// api.do is what the runner collects. tick() returns nothing, and nothing
// reads it - returning an array here would be discarded (§4.4).
tick();
