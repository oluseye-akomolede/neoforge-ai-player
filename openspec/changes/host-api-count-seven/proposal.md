# Proposal: the host API is seven functions, not six

## Why

The live spec `bot-coded-agents` says a script reaches the world through the
"six" `api` methods in three separate requirements. That was true before
`script-lookups-and-results` added `api.result`; since that change the runner
binds **seven**:

| method | `src/binding.js` |
|---|---|
| `do` | :328 |
| `say` | :355 |
| `send` | :364 |
| `recall` | :395 |
| `result` | :412 |
| `remember` | :419 |
| `log` | :440 |

`MAX_HOST_CALLS` is still 8 per tick (`src/binding.js:32`) — the count of
distinct functions and the per-tick call budget are different numbers, and
adding `result` changed only the first.

## Why this is a separate change

`script-lookups-and-results` could not fix this on archive. Its delta is
ADDED-only — one `## ADDED Requirements` section, no `MODIFIED` and no
`REMOVED` — so archiving appends new requirements and leaves existing ones
untouched. The three stale requirements predate that change and are not among
the ones it adds, so they need a MODIFIED delta of their own.

The trail is: `script-lookups-and-results` added `api.result` and re-anchored
its own prose to seven host functions, but the three live requirements that
describe the surface were never restated.

## What changes

Three requirements, and nothing else in the spec:

1. "The Planner MAY Author A Script As The Plan For A Goal" — two mentions
   (the "six-method `api` surface" paragraph, and the "six `api` methods"
   scenario).
2. "A Written Script MUST Pass A Dry Tick Before It Is Bound" — one mention.
3. "A Planner-Written Script's Source Is Logged When It Binds" — one mention,
   in the sentence that spells the surface out as "the six host calls and
   `look`".

In each, only the count changes to seven, and where the surface is enumerated
`result` is added. No obligation is restated or reworded.

## What does not change

- The unrelated "over six" in a log-line example (`(no additional)`). That is a
  different sentence about a log message, not about the `api` surface.
- `MAX_HOST_CALLS = 8` and every budget (`do:30/min`, `say:30/min`,
  `send:20/min`) — untouched by this change and unrelated to the count.
- Every scenario's GIVEN/WHEN/THEN semantics: the scenarios are carried over
  verbatim except for the number and the added name.

## Out of scope

The Java and Javascript code-cite re-anchoring carried over from the
`script-a2-cite` row. This change is spec prose only.
