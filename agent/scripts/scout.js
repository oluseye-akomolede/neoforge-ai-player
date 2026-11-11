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

  // Only act once we are actually healthy enough to move. A starved or hurt
  // bot acting on a stale plan is how a bot walks into lava while it is
  // already fleeing something.
  var health = snapshot.health;
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
  // The coordinates here come from this script, not from a fixture. If a
  // future edit deletes this object, the parity test in 8.2 must fail rather
  // than silently compare two empty bodies.
  return [
    { kind: "STORE_ALL" }
  ];
}

// The runner calls the script body per tick; returning the array above is the
// whole contract. Kept as a named function and invoked explicitly so a syntax
// error surfaces as a script failure rather than as an empty action list.
tick();
