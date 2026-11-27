# Review: A2 declaration parser fix (`681d215`)

**Verdict: FAIL — one blocking defect (F-1).** The fix does what the row says for
the cases it names, and every number in the row reproduces. But the new
comment-masking pass silently drops the declaration whenever a comment contains an
odd number of apostrophes, and a script then binds with **zero queries** and no
error. That is the same live-failure class (`Axiom's line 3 was a comment`) the
commit exists to end, arriving through a different door.

- Repo: `neoforge-ai-player`, branch `hotfix-declared-query-reads` off `9219b3d`
- Reviewed rev: `681d215` (2 files, +180/-15: `agent/script_tick.py`, `agent/test_declared_queries.py`)
- Row: `qitem-20261127112215-e39568d3`
- Base: `9219b3d` (host-api-count-seven archived)

Everything below was measured by me from a scratch extraction of `681d215`, not read
from the row body. Scratch dir removed.

## What the row claims, and which claims reproduce

| Claim | Result |
|---|---|
| `test_declared_queries` 42/42 | **reproduced** — Ran 42, OK |
| with `test_script_tick`, `test_result_delivery` → 113/113 | **reproduced** — Ran 113, OK |
| spec's own example binds and yields its queries | **reproduced** — returns `[{'name':'ore','kind':'blocks','id':'minecraft:iron_ore'}]` |
| a comment mentioning `look.queries` no longer refuses | **reproduced for the apostrophe-free case** |
| `api.queries = [...]` still refused | **reproduced** — `must be a bare assignment, not a property` |
| duplicate / trailing junk still refused | **reproduced** (existing tests) |

The suite needed `unittest`, not pytest — this VM has no pytest installed. Run as
`python3 -m unittest ...` from `agent/`. **Not** `python3 -I`: the `-I` flag drops the
script dir from `sys.path` and every module errors on import.

## F-1 (blocking): a comment with an odd number of apostrophes silently drops the declaration

### The measurement

A bare valid declaration, preceded by a comment containing N apostrophes:

```
apostrophes in // comment   ->  queries bound
  1   ->  0        <- script binds with ZERO queries, no error
  2   ->  1
  3   ->  0
  4   ->  1
  5   ->  0
  6   ->  1
```

Clean parity dependence. Odd → the declaration is gone; even → correct. Nothing
raises, nothing logs. The tick simply runs with no query data and `look.queries.ore`
is absent at runtime.

The trigger is not exotic — it is this repo's house style. `agent/scripts/scout.js`
at `681d215` has `runner's`, `enum's`, `producer's`, `planner's` in its comments.
The row's own live failure was *"Axiom's line 3 was a comment"* — an apostrophe in a
comment is precisely the situation under discussion.

### The mechanism (measured, not inferred)

`_find_declaration` does `masked = _mask_comments(_strip_strings(source))`.

`_strip_strings` blanks string bodies, and it treats an apostrophe in a comment as
opening a string. For `// it's fine` it produces:

```
"// it'___________________________________"
```

— the apostrophe survives, everything after it is blanked. `_mask_comments` then
runs on that text, sees the lone `'`, opens a string, and blanks to EOF:

```
'_________________________________________'
```

The declaration is inside the blanked region. With an **even** number of apostrophes
the first pairing closes before the declaration, so the text is coincidentally spared.

The docstring states the opposite of what happens:

> "strip strings first, then comments, and neither pass can be fooled by the other's
> payload."

Measured, the first pass's *output* is exactly what fools the second. Each pass is
correct on raw source — `_mask_comments(src)` alone handles the same comment fine.
The composition is what is wrong, and no test covers a comment containing a quote of
any kind.

### The existing tests cannot see it

All 42 pass with F-1 present, because every comment fixture in the suite is
apostrophe-free (`// look.queries.ore`, `/* look.queries */`). The suite tests the
comment *mentioning* the feature; it never tests a comment that is ordinary prose
about the script.

## A second finding, lower severity: compound assignment is not refused

The write-refusal fires only on a **lone** `=`, with `==` explicitly excluded. So:

| source | result |
|---|---|
| `api.queries = [...]` | REFUSE (correct) |
| `api.queries += [...]` | **ACCEPT** |
| `look.queries \|\|= [...]` | **ACCEPT** |
| `look.queries ??= [...]` | **ACCEPT** |

I did **not** count these as blocking, and I want to be explicit about why rather than
bury it: the spec's prohibition is on a dynamic *declaration*, and `+=` / `||=` on an
undeclared `queries` cannot construct a declaration the agent has not validated — the
value stays `undefined` and the array that matters is still the literal one the parser
read. So this is refuse-and-should-have-refused cleanliness, not a bypass of the
validated set. If the implementer disagrees with that reading, the fix is cheap (also
reject `+`, `|`, `?` immediately before `=`); I am not holding the deploy for it.

## The fix I verified, not just proposed

Mask comments **first**, on raw source, then strip strings:

```
n apos: declaration visible   old=False   new=True     (n=1)
                              old=True    new=True     (n=2)
                              old=False   new=True     (n=3)
string containing both "//" and "'" : declaration still visible -> True
```

Both passes must be string-aware over raw text; the defect is that the second one
sees already-blanked text. I tested this in the scratch extraction rather than
reasoning about it, and the regression test that pins it should be a comment
containing exactly one apostrophe, asserting the declaration still binds.

## On the row's spec-delta question

The row asks whether this needs a delta. **No** — and I agree with the builder's own
reading. The spec already requires `look.queries.<name>` to be readable and already
requires a dynamic declaration to be refused; the parser was wrong against a spec that
was right. "A comment is not a declaration" is a *clarifying* scenario, not new
behaviour, and adding it would put a scenario in the spec that describes an
implementation invariant rather than an observable requirement. Not a drop, not an
omission. I would take it as a comment in the code, which the `_mask_comments`
docstring already does — but note that the docstring's stated guarantee (F-1) is
currently false, so it needs correcting either way.

## Instrument notes (mine, not the change's)

- I first looked for this rev in `agent-script-runner` because the row said "agent/"
  and the path looked like the runner's. It is a **neoforge-ai-player** commit; the
  `agent/` directory is that repo's Python agent. Confirm the repo before concluding
  a rev is missing.
- Three successive probes returned "REFUSE" for cases that should accept, because my
  fixture declaration omitted a required field (`kind` needs `id`). I was measuring
  the kind validator, not the parser. Corrected to a fully valid declaration before
  drawing any conclusion — the first two rounds of output were my bug, not findings.
- `python3 -I` produced 3/3 module import errors. That is the documented `-I`
  `sys.path` effect, not a defect in the tests.

## Summary

The fix is right in intent and correct for apostrophe-free comments, and all the
row's numbers reproduce. **F-1 blocks**: an odd number of apostrophes in a comment —
ordinary prose in this codebase's own scripts — makes the declaration vanish silently
and the script binds with no queries. That is the live failure this commit set out to
fix, reappearing through the masking order. The compound-assignment gap is
non-blocking and I said why. The spec needs no delta. I would not deploy this until
F-1 is fixed and a one-apostrophe regression test is in the suite.
