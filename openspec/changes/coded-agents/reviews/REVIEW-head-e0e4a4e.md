# Head confirm — coded-agents at e0e4a4e

Row: qitem-20261110102428-c883b9c0
Reviewed: e0e4a4e (head), diffed against 7698f81 as the lead required.
Prior: PASS at 7698f81 (`REVIEW-gate-7698f81.md`).
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-10T10:28Z

## Verdict: PASS — 1.4 may be ticked at e0e4a4e

### Diff scope: as constrained, nothing else

`git diff 7698f81..e0e4a4e -- openspec/` shows exactly two files and two
concerns:

1. `spec.md` — the `api.log` exclusion removed from the cardgame-calls list at
   `:147`, plus explanatory prose at `:122` and `:152`.
2. `tasks.md` — the `1.4` untick.

No other hunk. The `api.remember`/`script.get`/limits-table text is untouched.

### The fix is correct

`api.log` no longer appears in any exclusion. It appears four times, all
consistent in role: the limits row (`:112`), the carried-across note (`:122`),
the shared-name note (`:152`), and the binding table (`:164`). My blocker is
cleared.

### The 1.4 untick is correct, and it is the sharper point

The untick rationale — "a PASS is a verdict on a specific revision" — is right,
and it is a correction of something I let slide. My PASS at 7371af7 could not
have covered `e68222f` (contract step, limits table, async host calls) or
`7698f81` (the api binding), both of which landed after it. When I wrote that
PASS I accepted the builder's argument that the delta "is confined to the item
the PASS named"; that is an argument about content, not a verdict about a
revision. The untick text now says so explicitly and forbids the inference.
Good.

### Validators

- `openspec validate coded-agents --strict` → "Change 'coded-agents' is valid"
- `openspec show coded-agents` → clean

## The one thing to fix before 1b freezes (not a gate on this commit)

The new prose contradicts itself about `api.log`'s limit:

- `:122` — "a shared name whose limit **was carried across** from cardgame's
  table because both games cap it the same way"
- `:152` — "The limit on it **differs per game** and is this binding's own"

Both cannot hold. The evidence says `:122` is the accurate one: the table row at
`:112` (`1 KB/line, 100 lines/min`) is cardgame's `:120`
(`1 KB per line, 100 lines per minute, 7-day retention`) with only the retention
term dropped. So it *was* carried across, and the one difference is that
minecraft's row omits retention.

Recommended: keep `:122`'s framing, and at `:152` either say the limit is shared
but minecraft's row does not yet state a retention period, or drop the "differs
per game" clause. If retention is deliberately absent, say that; a missing term
that is not named is the kind of gap an implementer fills by copying the other
game's number.

Not a re-gate: it is prose in a paragraph that no scenario quantifies over, and
the frozen contract is 1b's job — but 1b.2 should not freeze while two
paragraphs disagree about whether a row is shared.

## Scope

Head confirm only. Nothing built, nothing run.
