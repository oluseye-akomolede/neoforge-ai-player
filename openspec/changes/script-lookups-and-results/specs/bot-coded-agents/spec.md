# bot-coded-agents — lookups and results

## ADDED Requirements

### Requirement: A Script Can Look Up What The Tick Already Saw

A script MUST be able to ask questions of the data the agent already sent for
that tick, through a `look` object installed beside `api`, and a lookup MUST
NOT spend a host call, reach the network, or reach the mod.

#### Scenario: A lookup answers from the snapshot
- **GIVEN** a tick whose snapshot carries `nearby.mobs` including a sheep
- **WHEN** the script calls `look.nearest({ kind: 'mob', type: 'sheep' })`
- **THEN** it returns the nearest sheep with its distance
- **AND** `hostCalls` for the tick is unchanged by the call

#### Scenario: A lookup beyond the snapshot says so
- **GIVEN** a snapshot whose `nearby.blocks` covers radius 8
- **WHEN** the script asks for a block within 40 blocks
- **THEN** the lookup MUST NOT return an empty list that reads as "nothing there"
- **AND** it MUST report that the search did not extend that far

#### Scenario: A lookup cannot act
- **GIVEN** the `look` object built for a tick
- **WHEN** its construction is inspected
- **THEN** it MUST hold no reference to `api`
- **AND** no lookup path MUST reach `accept()`, the function that spends the
  host-call budget

#### Scenario: A lookup result is a copy
- **GIVEN** a lookup that returned a list
- **WHEN** the script mutates that list
- **THEN** a second lookup in the same tick MUST be unaffected

#### Scenario: A dry tick sees the same lookups
- **GIVEN** one snapshot and one script
- **WHEN** the script is dry-ticked and then live-ticked
- **THEN** every lookup MUST return the same value in both

### Requirement: A Script's Result Reaches The Planner On Stated Triggers Only

A script's return value MUST be delivered to the planner when the script
reports completion, when it errors, or when it states an escalation — and on
no other tick.

#### Scenario: A completed goal delivers one result
- **GIVEN** a script that returns `{ done: true, ... }`
- **WHEN** it is ticked repeatedly
- **THEN** exactly one result MUST be delivered
- **AND** the binding MUST be released

#### Scenario: An error delivers a result rather than only a log line
- **GIVEN** a script whose tick fails
- **WHEN** the agent processes the failure
- **THEN** a result MUST be delivered to the planner

#### Scenario: A loop cannot re-trigger the planner every tick
- **GIVEN** a script that returns `done: true` on every tick
- **WHEN** it runs for ten ticks inside one hour
- **THEN** at most 4 results MUST reach the planner
- **AND** the count dropped by the per-bot hourly cap MUST be recorded

#### Scenario: A result has a size cap
- **GIVEN** a script returning more than 2 KiB of JSON
- **WHEN** the result is delivered
- **THEN** it MUST be truncated with a marker
- **AND** it MUST NOT be dropped

#### Scenario: The planner reads a result without an extra call
- **GIVEN** a delivered result
- **WHEN** the planner next runs
- **THEN** the result MUST appear in that call's prompt
- **AND** no additional planner call MUST be made to carry it

#### Scenario: Logs and actions are not results
- **GIVEN** a script that calls `api.log` and `api.do` and returns nothing
- **WHEN** the tick completes
- **THEN** no result MUST be delivered
