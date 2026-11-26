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

Four requirements, and nothing else in the spec:

1. "The Planner MAY Author A Script As The Plan For A Goal" — two mentions
   (the "six-method `api` surface" paragraph, and the "six `api` methods"
   scenario). Count only.
2. "A Written Script MUST Pass A Dry Tick Before It Is Bound" — one mention.
   Count only.
3. "A Planner-Written Script's Source Is Logged When It Binds" — one mention,
   in the sentence that spells the surface out as "the six host calls and
   `look`". Count only.
4. "The Script Prompt Names The Host API The Sandbox Binds" — the fourth stale
   mention, and the only one that is an **enumerated exact set** rather than a
   count: "the sandbox binds exactly `do`, `say`, `send`, `recall`, `remember`,
   `log`". `result` is missing, so the set is false and the requirement's own
   scenario ("every method the runner binds is named by the prompt") fails.
   Two of its cites were also wrong: `binding.js:109-135` is
   `createBotState`/`createTickState` and contains no `api` surface (the `api`
   object is `:327-496`, with `result` at `:412`), and `engine.js:660-680` is a
   `finally` block in `#evalSource`, not the snapshot global (`#installSnapshot`
   is `:737-850`). This requirement gets `result` added to the set, the date
   re-stamped, and both cites corrected. Its scenarios are unchanged.

In requirements 1–3 only the count changes. Requirement 4 is the one place the
surface is enumerated, and `result` is added there. No obligation is restated
or reworded; no scenario is added, removed or renamed.

## What does not change

- The unrelated "over six" in a log-line example (live `:1144`). That sits in a
  different requirement about a log message, not about the `api` surface, and is
  outside all four ranges.
- `MAX_HOST_CALLS = 8` and every budget (`do:30/min`, `say:30/min`,
  `send:20/min`) — untouched by this change and unrelated to the count.
- Every scenario's GIVEN/WHEN/THEN semantics: the scenarios are carried over
  verbatim except for the number and the added name.

## Out of scope

The Java and Javascript code-cite re-anchoring carried over from the
`script-a2-cite` row. This change is spec prose only.
