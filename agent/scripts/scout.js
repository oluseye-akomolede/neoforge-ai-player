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
    return [];
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
    return [];
  }

  // The task we are on. `snapshot.task` is the directive the agent is
  // currently running, so a script does not start a second job underneath one
  // already in flight.
  if (snapshot.task) {
    return [];
  }

  // THE ACTION. This is the one 8.2 compares, and its argument form matters:
  // `STORE_ALL` takes an OPTIONAL coordinate triple (StoreAllBehavior.java:62
  // `if (directive.hasLocation())`), and when it has one it stores into that
  // specific container and moves the bot there (:171). Leaving the coordinates
  // off asks the mod to choose, which is the form the planner's own seed match
  // produces (agent.py:1888 -- its pattern has no capture groups).
  //
  // This script emits the COORDLESS form on purpose, and 8.2 pins that form.
  // Every producer in this repo emits it coordless: the planner's own seed
  // match (agent.py:1888) returns a bare object because its pattern has no
  // capture groups, and the mod's seed specs put the coordinates on AREA_LOOT
  // with STORE_ALL bare beside it (SkillRegistry.java:154). The coordless form
  // is therefore the plausible call, and a constructed fixture should
  // construct that one.
  //
  // The directive here comes from THIS script, not from the test harness. If a
  // future edit returns nothing, the 8.2 parity test must fail rather than
  // silently compare two empty bodies.
  return [
    { kind: "STORE_ALL" }
  ];
}

// The runner calls the script body per tick; returning the array above is the
// whole contract. Kept as a named function and invoked explicitly so a syntax
// error surfaces as a script failure rather than as an empty action list.
tick();
