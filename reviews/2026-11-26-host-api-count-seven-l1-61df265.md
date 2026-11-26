# Review: host-api-count-seven L-1 fix (`61df265`)

**Verdict: PASS.** Both halves of L-1 are handled the way I recommended. M5 is dead,
M3 is documented rather than fixed, and the docstring now states the property the check
actually establishes. One cosmetic message defect (N-1), not worth a round.

- Repo: `neoforge-ai-player`, branch `spec-host-api-seven`
- Reviewed rev: `61df265` (parent `f457c42`; base `c920f6a`)
- Row: `qitem-20261126232014-61459f7d2207cc6b`
- Prior review: `...-cites-harness-f457c42.md` (L-1 raised there)

Extracted from `61df265` itself into an isolated dir and run with `python3 -I`. The
delta is byte-identical to `f457c42` (`git diff --quiet` → identical); the only changed
file is `check_cites.py`. Both strict validates rc=0.

## L-1 closed on both halves

**M5 is dead.** Each `CHECKS` cite is now asserted present in the delta before it is
checked, and an entry whose cite has left the prose fails as a stale row. Re-driven:

| Mutant | `f457c42` | `61df265` |
|---|---|---|
| M5 cite deleted from prose, entry left | rc=0 (blind) | **rc=1** "stale CHECKS entries (cite left the prose)" |
| M3 sentence verb → "spawns", cite untouched | rc=0 (blind) | rc=0, **documented** |
| M4 new cite added to delta | rc=1 | rc=1 (unchanged) |
| M1 fleet entry → `:165` | rc=1 | rc=1 (unchanged) |
| Baseline | rc=0 | rc=0 |

**M3 is documented, and that was the call I recommended.** The docstring now states the
verb phrases are string literals, that the delta is read only to harvest cite tokens and
confirm presence, and that the check therefore binds **code to claim, not claim to
prose**. It names my M3 case explicitly — a sentence reworded while its cite stays put
leaves the check green and the sentence possibly false — and says reading the sentences
is still required. Deriving the verbs from prose is more machine than this earns, and I
agree with declining it.

Two smaller things landed that I asked for and had not specified as requirements:

- **The manual-aid statement.** The docstring now opens by saying `git grep` finds no
  caller and that it must not be read at archive time as "the cites are now enforced".
  That was the point of my `git grep` finding and it is now where the next reader will
  hit it.
- **The green line no longer overclaims.** A passing run now ends "this binds code to
  these claims, not the prose to them. The sentences still need reading." A green run
  cannot be quoted for more than it proves — that is the failure that produced this
  whole sequence, so putting the limit in the output rather than only the docstring is
  the right place for it.
- Relabelling the column from "verb phrase from the sentence" to "the CLAIM this pattern
  encodes" is a correct fix in itself: the old label was the docstring's error in
  miniature.

## N-1 (cosmetic, mine, not worth a round)

If the prose narrows a governed cite to a sub-range — I changed `binding.js:342-346` to
`342-343` — the run fails, but reports it as *"stale CHECKS entry"*. The `CHECKS` entry
is not stale; the prose changed and the old entry no longer matches exactly. The
presence set stores exact `(file, start, end)` tuples, so any range drift appears as a
vanished entry. It fails closed, which is the safe direction, and it is only the message
that misleads. A one-line wording change ("CHECKS entry does not match any cite in the
delta") would cover both causes.

I include it for completeness, not as a request. It does not affect any result.

## Re-verified at `61df265`

- `git diff --quiet f457c42 61df265 -- …/spec.md` → **identical**; `--name-only` lists
  only `check_cites.py`. So the 16/16 scenario table, the zero-"six" count, the
  seven-method enumeration and the `fleet.js:166` sentence verified at `f457c42` are
  unchanged, and I am not re-deriving text that did not move.
- `openspec validate host-api-count-seven --strict` → rc=0; `bot-coded-agents --strict`
  → rc=0.
- Baseline 13 claims clean, rc=0, with the honest closing note.

## On the builder's self-report

They said they checked my M3/M5 reading in the code before changing it, and describe
M5 as "CHECKS entries were iterated unconditionally" and M3 as "the delta was opened at
what is now :104-106 and used only for `present`". Both are accurate to the code as it
was. They also accepted the sharper framing — the patterns encode the action correctly,
the docstring described a wider guarantee than the code makes — which is the useful half
of the finding and the part most likely to repeat.

## Summary

L-1 is closed: M5 fails now, M3 is honestly documented, the manual-aid status is written
where a reader will meet it, and the success output states its own limit. The only
remaining defect is a misleading failure message for exact-range drift, which fails
closed. Nothing here blocks the archive, and the archive remains the lead's call.
