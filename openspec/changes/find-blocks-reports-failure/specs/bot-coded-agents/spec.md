# bot-coded-agents — a failed block search is not an empty one

## ADDED Requirements

### Requirement: A Failed Block Search Reaches The Script As A Failure, Not An Empty List

A declared `blocks` query whose mod answer carries an `error` key MUST reach the
script as `{ ok: false, reason: "error", message: <the mod's own text> }` for
that query only, and MUST NOT reach it as `{ ok: true, matches: [] }`. A
declared `blocks` query whose mod answer is `{blocks: []}` with **no** `error`
key MUST stay `{ ok: true, matches: [] }`, because that is a search that ran and
found nothing — the opposite fact.

**This requirement is only meaningful once the mod sends the error key.** It is
written as ADDED, not MODIFIED, because the requirement it qualifies — "A Script
Declares The Searches It Needs And Reads Them As `look.queries.<name>`" — lives
today only in the pending change `script-lookups-and-results`
(`openspec/changes/script-lookups-and-results/specs/bot-coded-agents/spec.md`)
and is not yet in `openspec/specs/bot-coded-agents/spec.md`. A MODIFIED header
naming it cannot be archived until that change is archived, so the two changes
have an order:

1. `script-lookups-and-results` archives first, putting the declared-queries
   requirement into the live spec.
2. This change archives after it.

The builder MUST NOT merge this change's spec delta into
`script-lookups-and-results` by hand; two unarchived changes touching one
requirement is how the archive step starts refusing deltas. If the lead would
rather land them together, the correct move is to archive
`script-lookups-and-results` first and then MODIFY here — either order is fine,
but the archiving order is fixed, and this change is second.

#### Scenario: A failed block search is not an empty block search
- **GIVEN** a declared `blocks` query, and the mod answering
  `{blocks: [], error: "findBlocks error: ..."}` because its search threw
- **WHEN** the tick runs
- **THEN** `look.queries.<name>` MUST be `{ ok: false, reason: "error" }`
- **AND** its `message` MUST carry the mod's own error text, so the planner can
  tell a broken search from a world with nothing in it
- **AND** the other declared queries MUST still be present and correct
- **AND** the tick MUST NOT fail because of it

#### Scenario: A genuine empty result stays a success
- **GIVEN** a declared `blocks` query, and the mod answering `{blocks: []}` with
  no `error` key because the search ran and found nothing
- **WHEN** the tick runs
- **THEN** `look.queries.<name>` MUST be `{ ok: true, matches: [] }`
- **AND** it MUST NOT carry `ok: false`, so the fix never turns a world with
  nothing in it into a reported failure

#### Scenario: The test drives the mod's answer, not a raising stub
- **GIVEN** the test for the scenarios above
- **WHEN** it is inspected
- **THEN** it MUST feed `{blocks: [], error: ...}` through
  `agent/script_tick.py`'s normaliser
- **AND** it MUST NOT stand in for this by making `find_blocks` raise, because a
  raising stub exercises the `except` branch rather than the error-key path the
  mod fix creates, and the guard could be deleted with the suite still green
