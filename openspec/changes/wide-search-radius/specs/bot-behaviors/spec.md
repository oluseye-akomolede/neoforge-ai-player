## MODIFIED Requirements

### Requirement: Escalating Search
Behaviors that search for blocks MUST use escalating search radii: 32 → 64 → 128 → 256 → 512 → 1024 blocks. Default starting radius is 256. A behavior MUST treat a caller-supplied radius as a maximum distance to search rather than as a starting shell: when the supplied radius is smaller than the first shell, the first shell MUST be clamped to it and the search MUST stop there rather than escalate past it.

#### Scenario: Search radius escalates on failure
- GIVEN a MineBehavior searching for diamond_ore starting at radius 256
- WHEN no diamond_ore is found within 256 blocks
- THEN the search radius MUST escalate to 512 blocks
- AND if still not found, escalate to 1024 blocks before falling back

#### Scenario: A supplied radius caps escalation
- GIVEN a WideSearchBehavior given a maximum radius of 64
- WHEN the first shell completes without a match
- THEN it MAY escalate to 64 blocks
- BUT it MUST NOT escalate to 128 blocks or beyond

## ADDED Requirements

### Requirement: Wide Search Radius
`WideSearchBehavior` MUST read a search radius from the `radius` key of the directive's `extra` map, and MUST fall back to the directive's top-level `radius` field when `extra.radius` is absent or unparseable. The supplied value MUST be clamped between a floor of 1 and a ceiling that leaves the default escalation intact, in the manner of `AreaLootBehavior.java:77`. When no radius is supplied at all the behavior MUST keep today's starting radius and escalation unchanged.

The behavior MUST report the radius it actually searched. A search stopped by a small supplied radius MUST NOT report the unclamped escalation value; reporting 32 blocks after searching 4 is a false statement to the user.

#### Scenario: A small radius searches only cells within it
- GIVEN a live request to find a target within 4 blocks without walking
- WHEN the directive carries `extra: {"radius": "4"}`
- THEN the search scans only the cells within 4 blocks of the centre
- AND it does NOT perform the 25-cell, 32-block sweep
- AND the number of cells scanned is 1 for a 16-block cell size

#### Scenario: extra.radius overrides the top-level field
- GIVEN a directive with a top-level radius of 256 and `extra: {"radius": "16"}`
- WHEN the search starts
- THEN the effective maximum radius is 16
- AND the first shell is clamped to 16 rather than 32

#### Scenario: No radius keeps today's behaviour
- GIVEN a directive with no top-level radius and no `extra.radius`
- WHEN the search starts
- THEN the first shell radius is 32
- AND escalation proceeds 32 → 64 → 128 → 256, stopping at the default ceiling of 256

#### Scenario: Failure reports the radius actually searched
- GIVEN a search with a maximum radius of 4
- WHEN the single shell completes without a match
- THEN the failure reason states 4 blocks
- AND it does NOT state 32 blocks

#### Scenario: The surfaces advertise the radius
- GIVEN the `goto_and_scan` skill seed and the L3 directive vocabulary
- WHEN the model reads either surface to compose a WIDE_SEARCH directive
- THEN both name `radius` as an accepted parameter
- AND both state that it is a maximum distance to search
