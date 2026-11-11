## ADDED Requirements

### Requirement: Fleet-Wide Orders

An order MAY be addressed to the whole fleet. A fleet order MUST be delivered to
every living fleet bot, and each bot MUST run its own independent plan for its
assignment — a failure on one bot MUST NOT abort the others.

A fleet order MAY be typed or free text (TEXT). A typed fleet order fans out
verbatim to every bot. A TEXT fleet order MUST first be partitioned: one L3 call
receives the fleet's per-bot personas and holdings summaries and returns one
short assignment per bot, where a bot MAY be assigned "skip". If the partition
call fails or its reply cannot be parsed, the order MUST fall back to verbatim
fan-out rather than being dropped.

Fleet orders carry a shared fleet id on the order wire so the dashboard can
render them as one umbrella with per-bot status.

#### Scenario: Typed fleet order fans out verbatim
- GIVEN several bots are online
- WHEN a typed fleet order is submitted to the fleet address
- THEN one order entry per living bot is created
- AND each bot runs the same order verbatim
- AND all entries carry a shared fleet id

#### Scenario: Text fleet order is partitioned per bot
- GIVEN a free-text fleet order and the fleet's personas and holdings
- WHEN the order is submitted
- THEN one L3 partition call assigns each bot a short instruction
- AND a bot whose assignment is "skip" is given no order
- AND the remaining bots each run their own plan

#### Scenario: Partition failure degrades to verbatim fan-out
- GIVEN the partition call errors or returns an unparsable reply
- WHEN the fleet order is submitted
- THEN every bot receives the original order text verbatim
- AND the order is not dropped

#### Scenario: One bot's failure does not abort siblings
- GIVEN a fleet order running across several bots
- WHEN one bot's plan fails
- THEN the other bots continue to completion
- AND the umbrella row shows per-bot status

### Requirement: Standing Orders

A standing order is a persistent watcher: a condition over observable state, an
action to fire when the condition is broken, and a recorded result. Standing
orders MUST be owned by the mod as definitions and by the agent as judgement.

The agent MUST evaluate standing orders on a periodic cadence. An action MUST
fire only when the condition is broken, the bot is idle, and the order's
cooldown has lapsed. A fired action MUST enter the same order lane as any other
order, so all downstream triggers still apply.

Repeatedly failing orders MUST back off exponentially and raise ONE inbox item
rather than firing continuously. A per-bot cap on standing orders MUST be
enforced with an honest refusal beyond the cap.

Watch types are `me_count`, `vault_count`, and `xp_level`.

#### Scenario: A broken condition fires the action once
- GIVEN a standing order "keep >= 32 quartz dust" with the network below 32
- WHEN the watcher evaluates the order on its cadence and the bot is idle
- THEN exactly one action is dispatched through the normal order lane
- AND the order records the fire and result

#### Scenario: An unbroken condition does not fire
- GIVEN a standing order whose condition currently holds
- WHEN the watcher evaluates the order
- THEN no action is dispatched

#### Scenario: Failure backs off instead of nagging
- GIVEN a standing order whose action keeps failing
- WHEN it fails repeatedly
- THEN the interval between attempts grows
- AND exactly one inbox item is raised, not one per failure

#### Scenario: Per-bot cap refuses honestly
- GIVEN a bot already at its standing-order cap
- WHEN another standing order is created for it
- THEN the creation is refused with a reason
