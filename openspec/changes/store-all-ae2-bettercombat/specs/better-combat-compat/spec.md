## ADDED Requirements

### Requirement: Better Combat Mod Detection
The system SHALL detect whether Better Combat is loaded at runtime and conditionally use its animation system for bot attacks.

#### Scenario: Better Combat present
- **WHEN** Better Combat is loaded (`ModList.get().isLoaded("bettercombat")` returns true)
- **THEN** bot attacks SHALL use Better Combat animation packets

#### Scenario: Better Combat absent
- **WHEN** Better Combat is not loaded
- **THEN** bot attacks SHALL use vanilla `ClientboundAnimatePacket.SWING_MAIN_HAND` (current behavior)
- **AND** the mod SHALL load and function normally without Better Combat classes

### Requirement: Weapon Animation Dispatch
When Better Combat is present, the system SHALL send the appropriate weapon-specific attack animation packet instead of vanilla swing.

#### Scenario: Bot attacks with BC-registered weapon
- **WHEN** a bot attacks an entity while holding a weapon that has a Better Combat animation registered
- **THEN** the Better Combat animation packet SHALL be broadcast to all online players
- **AND** the vanilla swing packet SHALL NOT be sent

#### Scenario: Bot attacks with non-BC weapon
- **WHEN** a bot attacks while holding an item without a Better Combat animation (e.g., bare fist, non-weapon item)
- **THEN** the vanilla swing animation SHALL be sent as fallback

#### Scenario: Animation visible to all players
- **WHEN** a Better Combat animation packet is broadcast
- **THEN** all online players with Better Combat installed SHALL see the correct weapon animation on the bot

### Requirement: Graceful Degradation
The Better Combat integration SHALL never cause combat to fail if the compat layer encounters an error.

#### Scenario: BC API error during animation dispatch
- **WHEN** the Better Combat compat layer throws an exception during animation lookup or packet construction
- **THEN** the system SHALL log a warning, fall back to vanilla swing, and continue combat normally
- **AND** combat damage SHALL NOT be affected by animation failures
