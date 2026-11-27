# api-http — a failed block search says so

## ADDED Requirements

### Requirement: A Failed Block Search Answers With An Error, Not A Bare Empty List

`POST /bot/{name}/find_blocks` MUST answer a search that failed distinguishably
from a search that succeeded and found nothing. A successful search MUST answer
`{blocks: [...]}`, empty or not, exactly as it does today. A search whose
`BotPlayer.findBlocks` call throws MUST answer with an `error` key naming the
failure beside its list, in the shape `scan_data` already uses on its own
failure path (`{blocks: [], count: 0, error: "..."}`, `HttpApiServer:1420`), so
the two outcomes are different bytes.

This exists because the two are byte-identical today. Measured at `2f019c0`:
`HttpApiServer:1117-1127` runs `bot.findBlocks` on the server thread, its
`catch` completes the future with `List.of()` and logs `findBlocks error`
(`:1124`), and the handler then answers `Map.of("blocks", boundedJoin(...))` —
there is no `error` key on any path. A planner that receives `{blocks: []}` from
a broken search concludes "nothing there" and plans on it. The failure is real:
`findBlocks` reads the level, the block registry and `formatBlockPos`, any of
which can throw.

The success path MUST NOT change — not its fields, not its status, not its
timing — because every caller of `/find_blocks` (the planner's query
functions and the agent's declared-queries runner) already handles
`{blocks: [...]}` and must keep working unmodified.

#### Scenario: A search that throws answers with an error key
- **GIVEN** a bot whose `findBlocks` call throws
- **WHEN** the agent posts to `/bot/{name}/find_blocks`
- **THEN** the response MUST carry an `error` key naming the failure
- **AND** it MUST still carry a `blocks` list, as it does today, so a caller that
  reads only `blocks` is not broken
- **AND** the response MUST NOT be a bare `{blocks: []}` with nothing else

#### Scenario: A genuine empty result carries no error key
- **GIVEN** a bot whose `findBlocks` call returns an empty list because nothing
  matched
- **WHEN** the agent posts to `/bot/{name}/find_blocks`
- **THEN** the response MUST be `{blocks: []}`
- **AND** it MUST NOT carry an `error` key, so a world with nothing in it is not
  reported as a broken search

#### Scenario: The success path is unchanged
- **GIVEN** a bot whose `findBlocks` call returns two blocks
- **WHEN** the agent posts to `/bot/{name}/find_blocks`
- **THEN** the response MUST be `{blocks: [<two blocks>]}` and nothing else MUST
  have changed about it
- **AND** this MUST be pinned by a test that would fail if a field were added to
  or removed from the success answer

#### Scenario: The failure is still logged and still bounded
- **GIVEN** a `findBlocks` call that throws
- **WHEN** the handler answers
- **THEN** the exception MUST still be logged at error level as it is today
  (`:1124`), because the log is where an operator sees why the search broke
- **AND** the handler's wait on the server thread MUST still be bounded by
  `boundedJoin`/`BoundedWait`, so a stalled thread is still a 503 with an `error`
  body and never a hang

#### Scenario: The deterministic half is unit-tested without Minecraft
- **GIVEN** the JUnit suite under `src/test/java/com/sigmastrain/aiplayermod/api/`
- **WHEN** the change is reviewed
- **THEN** the failure and empty answers MUST be distinguishable from a plain
  `CompletableFuture` and a null error, with no Minecraft classpath, in the shape
  `BoundedWaitTest` already establishes
- **AND** the end-to-end answer (a real search throwing in a real world) belongs
  to the deploy run plan, and the proposal MUST say so rather than implying the
  JUnit test proves it
