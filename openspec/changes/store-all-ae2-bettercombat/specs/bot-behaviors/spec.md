## ADDED Requirements

### Requirement: Store All Behavior State Machine
StoreAllBehavior SHALL implement the Behavior interface with phases: VALIDATE → SCAN_INVENTORY → FIND_CONTAINER → DEPOSITING → NEXT_ITEM → COMPLETE.

#### Scenario: Full inventory dump lifecycle
- **WHEN** a bot starts a STORE_ALL directive with 5 different item types in inventory
- **THEN** the behavior iterates through each non-essential item type
- **AND** deposits each into the nearest container with space
- **AND** returns SUCCESS when all depositable items have been stored

### Requirement: ME Store Behavior State Machine
MEStoreBehavior SHALL implement the Behavior interface with phases: VALIDATE → FIND_INTERFACE → INSERTING → COMPLETE.

#### Scenario: ME store lifecycle
- **WHEN** a bot starts a ME_STORE directive
- **THEN** the behavior scans for ME Interface blocks, teleports to the nearest, inserts items via IItemHandler, and returns SUCCESS

### Requirement: ME Withdraw Behavior State Machine
MEWithdrawBehavior SHALL implement the Behavior interface with phases: VALIDATE → FIND_INTERFACE → EXTRACTING → COMPLETE.

#### Scenario: ME withdraw lifecycle
- **WHEN** a bot starts a ME_WITHDRAW directive
- **THEN** the behavior scans for ME Interface blocks, teleports to the nearest, extracts items via IItemHandler, and returns SUCCESS

## MODIFIED Requirements

### Requirement: Phase-Based State Machines
Each Behavior MUST be implemented as a phase-based state machine that returns BehaviorResult (RUNNING, SUCCESS, FAILED) on each tick.

#### Scenario: Behavior returns result each tick
- GIVEN a MineBehavior in the "mining" phase
- WHEN the server ticks
- THEN the behavior MUST return RUNNING while mining is in progress
- AND return SUCCESS once all requested blocks have been mined

#### Scenario: StoreAll behavior returns result each tick
- GIVEN a StoreAllBehavior in the "depositing" phase
- WHEN the server ticks
- THEN the behavior MUST return RUNNING while items remain to deposit
- AND return SUCCESS once all non-essential items have been stored

#### Scenario: ME behaviors return result each tick
- GIVEN a MEStoreBehavior in the "inserting" phase
- WHEN the server ticks
- THEN the behavior MUST return RUNNING while insertion is in progress
- AND return SUCCESS once all requested items have been inserted or the network is full
