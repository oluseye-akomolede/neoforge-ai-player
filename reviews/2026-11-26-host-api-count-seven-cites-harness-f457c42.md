# Review: host-api-count-seven F-1 fix + cite harness (`f457c42`)

**Verdict: PASS.** The `fleet.js` cite is fixed and fixed well. The harness is a real
improvement and its two claimed failure paths genuinely bite — I drove them. It has one
structural limit (L-1) that both its docstring and the row body overstate, which matters
for how much trust it gets at archive, not for whether this change is right.

- Repo: `neoforge-ai-player`, branch `spec-host-api-seven`
- Reviewed rev: `f457c42` (parent `dbf2fea`; base `c920f6a`)
- Row: `qitem-20261126231847-e150236ed0afdf0f`
- Prior reviews: `...-315f12e.md`, `...-f1-cec433d.md`, `...-r1-de009e5.md`,
  `...-f1-full-dbf2fea.md` (F-1 raised there)

Note on scope: this change is **not in my branch's HEAD** — `git cat-file -e
HEAD:openspec/changes/host-api-count-seven` fails on `minecraft-wt-qwen`, since the work
lives on `spec-host-api-seven`. Everything below was extracted from `f457c42` itself
(`git show f457c42:<path>`) into an isolated dir and run with `python3 -I`.

## F-1 is closed

The sentence now reads "the `#ensure` lookup at `fleet.js:166` reuses the worker across
requests", and `fleet.js:166` is `let worker = this.#workers.get(botId);` at `b48c4ad`.
That is the fix I asked for, done the better of the two ways I offered: it names the
lookup *and* cites the line, so neither the symbol nor the verb can drift alone.

The builder's account of their own error is accurate and I agree with all of it — 165 is
a definition, `:182` discards the dead worker it looked up, `:207` spawns only on a miss,
so `:166` is the whole of "reuses". The commit message records it honestly.

## The harness, tested rather than read

`openspec/changes/host-api-count-seven/check_cites.py` pairs each of 13 cites with the
verb phrase of its clause and a regex the landing line must match, and fails a delta cite
that no entry governs. Baseline at `f457c42` / runner `b48c4ad`:

```
13 cites checked against the verb of their own sentence
all clean                                    RC=0
```

I then drove five mutants. The two the builder claims, and three they did not:

| Mutant | What it changes | RC | Verdict |
|---|---|---|---|
| M1 | fleet entry pointed back at `:165` | 1 | **bites** — `FAIL fleet.js:165` |
| M2 | a delta cite changed to `binding.js:314` | 1 | **bites** — `1 cite(s) ... NO verb check` |
| M4 | a new cite (`engine.js:999`) added to the delta | 1 | **bites** — reported ungoverned |
| M3 | **the sentence's verb** changed to "spawns", cite untouched | **0** | **blind** |
| M5 | the `fleet.js:166` cite **deleted from the prose**, table entry left | **0** | **blind** |

M1, M2 and M4 confirm the claim. M4 in particular is a good property — it catches a new
cite added anywhere in the delta, not only in the 13 known positions.

## L-1 — the checker never reads the sentence it names

The docstring says the check asks whether "the line it lands on satisfies **that phrase**".
It does not: the verb phrases are string literals in `CHECKS`, and the delta is opened
only to harvest cite *tokens* (line 79-81). Confirmed by reading the code, not inferred
from M3 alone.

The consequences are exactly M3 and M5:

- **M3** — if the prose verb drifts to "spawns" while the cite stays on the `:get` lookup,
  nothing notices. `:207` is the spawn, so that sentence would be **false** and the
  checker green. This is not hypothetical: it is the same drift, one layer up, that
  produced both the original 14 and `fleet:165`.
- **M5** — a `CHECKS` entry whose cite has left the prose is still run and still passes.
  The table can only decay toward stale entries.

So the true property is: *"each of these 13 hardcoded claims holds against the runner at
this rev, and no delta cite is outside that list."* That is genuinely valuable and it is
what would have caught `fleet:165` first time — but it is one-directional. It binds the
code to the claim; it does not bind the claim to the prose.

**Suggested fix, small:** in the loop, assert `cite in text` before checking, and fail
`"cite absent from delta"` if not (kills M5). For M3, either move each verb phrase into
the delta as an anchor the script greps for, or state the limit in the docstring so the
next reader doesn't believe "that phrase" means the sentence. I'd take the assertion plus
an honest docstring; deriving verbs from prose is a bigger machine than this needs.

**None of this blocks.** The 13 patterns are correct, and every one I sampled reads the
right line. It is a claim-scope defect in the harness's own documentation, and the harness
is supporting evidence rather than the change itself.

## Re-verified at `f457c42`

- All 13 cites resolved at `b48c4ad` and read against their verb phrases — consistent
  with my independent pass at `dbf2fea`, plus `fleet.js:166` now correct.
- Delta touched is the spec file plus the new script; `openspec/specs/` untouched.
- Scenarios and the seven-method enumeration were verified at `dbf2fea` and the only spec
  change since is the one-sentence fleet fix above, so they are unchanged.
- The harness is **new surface in the change directory**. It is not wired into anything
  that runs automatically — it is a manual script with a usage line. That is fine for its
  purpose (a reviewer's aid), but it is not a gate, and the row should not read as though
  the cites are now enforced.

## On their "one honest limit"

They wrote that the verb pattern is their own assertion about each line, so the harness
"does not make the reading correct on its own, so a re-derivation by you still overrides
it." That is right and it is the reason I re-derived all 13 rather than running the
script and stopping. It is also the part that makes L-1 worth stating: they correctly
identified that the *content* of the pattern is a claim, and did not notice that the
*scope* of the claim is narrower than the docstring says.

## Summary

F-1 closed; the fleet cite is right and the sentence now names the lookup by both symbol
and line. The harness is a real gain and its two advertised failure paths plus a third
(M4) bite as claimed. It does not read the prose, so a drifted sentence verb (M3) or a
cite removed from the prose (M5) passes silently — one assertion and an honest docstring
would close it. Archive remains the lead's call and I would not hold it for L-1.
