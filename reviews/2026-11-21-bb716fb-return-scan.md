# Review — bb716fb: return inside a block (trial 4.2 blocker)

- **Rev reviewed:** `bb716fb` (on `bdaeeb7`), branch `minecraft-wt-deepseek`,
  worktree `~/minecraft-wt-deepseek/agent-script-runner`. Tree clean at review time.
- **Verdict:** **FAIL** — the reported blocker is fixed, but the new scanner
  has an **under-wrap** of the same kind, and under-wrap is the direction the
  row says breaks a bot's script.

## What is right

- `if (x) { return; }` at top level is now recognised as the script's body and
  runs. Confirmed through the real `Sandbox.evaluate`, not a copy of the logic:
  `if (1) { return 'BODY'; }` → `ok value="BODY"`.
- The reported shape and its neighbours all pass: else-if, nested blocks, for,
  do-while, switch/case, labelled block, try/finally, `try {} catch (e) {} return`.
- IIFEs keep their value: `(function(){ return 7; })()` → `7`;
  `(() => { return 7; })()` → `7`. That is the over-wrap case the commit
  deliberately protects, and it holds.
- `obj.return`, `{ return: 1 }`, and `return` inside strings, templates and
  comments are all correctly not treated as statements.
- Suite: `# tests 177 # pass 177 # fail 0`, rc=0 — the builder's figure is
  exactly right.

## F-1 (blocking): `function` used as a property key hides a real top-level return

The scanner sets `pendingFunction = true` whenever it sees the token
`function` in identifier position, and attaches it to the **next** `{`. When
`function` is a **property key** (not the start of a declaration), that next
brace is not a function body — but it is consumed as one anyway, so it pushes
`true` onto `fnStack` and the real top-level `return` inside it is counted as
function-internal and missed.

Reproduction through the real `Sandbox.evaluate` (`python`-free, `node -B` not
needed; each case is the whole source):

| source | result |
|---|---|
| `const o = { a: 1 }; if (1) { return 'BODY'; }` | `ok value="BODY"` (baseline) |
| `const o = { function: 1 }; if (1) { return 'BODY'; }` | **`ERR: return not in a function`** |
| `const o = { function: 1 }; { return 'BODY'; }` | **`ERR: return not in a function`** |
| `if (({ function: 1 })) { return 'BODY'; }` | **`ERR: return not in a function`** |
| `const o = { function: 1 }; return 'BODY';` | `ok value="BODY"` (no block: unaffected) |

The only difference between the first two rows is the property name. The
failure is exactly trial 4.2's symptom — `return not in a function` — reached
from a different trigger.

**Realistic bot shapes hit it**, not just contrived ones:

```
const ops = { function: 'mine' };
if (ops.function === 'mine') { return 'BODY'; }   -> ERR: return not in a function

const ctx = { function: 1 };
for (const k in ctx) { return 'BODY'; }           -> ERR: return not in a function
```

A dispatch table or record with a `function` field is ordinary script code. A
planner that writes one and returns inside a condition gets its bind refused.

**Why the tests miss it:** the commit's own guard test covers `obj.return` and
`{ return: 1 }` — the `return` token — but nothing covers `function` as a key.
`grep -rn "function:" test/*.mjs` returns no test. So 177 green is consistent
with the bug.

**Direction:** this is under-wrap (a real top-level return missed), the
failure mode the row says to hunt and weigh more heavily, because it breaks a
bot's script rather than merely losing a value the 11-10 rule discards.

**Fix sketch:** the `function`/`=>` detection needs to distinguish an
*expression-start* position from a key/member position, the way the `return`
guard already does with `src[i-1] !== "."` and `src[i+6] !== ":"`. The
cheapest correct guard is to skip a `function` token that is immediately
followed (after whitespace) by `:` or that follows a `.`, and to require a
declaration/expression start character before it. The `=>` branch has the
mirror risk: `=>` inside an object literal's value is real, but `=>` cannot be
a key, so it is safe today; the `function` token is the one that needs it.

## F-2 (not blocking, same fix): `pendingFunction` is not cleared on failure to consume

If a `function` token is followed by a `{` that is *not* its body — which is
exactly the F-1 case, and also `function f() /* c */ {` is safe only because
the brace does eventually arrive — the flag already mis-attaches. A second
reset when the token turns out not to open a body would make the invariant
local rather than positional. Fold into the F-1 fix.

## Over-wrap probe — clean

I hunted the reverse direction too and found none. These all keep their value
(so the scanner correctly did NOT wrap):

- `("a => b").length` → 6; `("function x(){ return 1; }").length` → 25
- `({ function: 5 }).function` → 5; `({f:1}).function ?? 'NONE'` → `"NONE"`
- `` `a => ${1}` `` → `"a => 1"`; `1 /* a => b */ + 2` → 3
- `((x) => x + 1)(41)` → 42; `((x) => ({ v: x }))(1)` → `{"v":1}`

Over-wrap is the benign direction per the row (the 11-10 rule discards the
value anyway), but it is clean, so no note needed.

## Under-wrap probes that PASSED (so the gap is narrow)

Every one of these was found correctly as a real top-level return:

- after an arrow-block member, a function inside an `if`, an object literal, a
  destructuring, a template with `${}`, a string containing `function`, a
  comment containing `function`, a regex literal, division
- async arrow block, multiple object methods, function as a default parameter,
  functions in an array, class expressions, IIFEs (both forms), nested arrows,
  arrow with no braces followed by a block, return inside an arrow inside an if
- `function` with a destructured parameter, with a default object parameter,
  a generator function, `class extends`, and a `function` keyword caught by a
  comment before its brace

So the scanner is right in the large majority of shapes; the `function`-as-key
case is the hole.

## Suites (bounded)

- `node --test --test-timeout=40000 "test/*.test.mjs"` (declaration read from
  `package.json`): `# tests 177 # pass 177 # fail 0`, rc=0.
- Probes driven through the exported `Sandbox` + `createLimitedRuntime`, same
  as `test/look-engine.test.mjs`; no source modified, worktree restored clean
  after each.

## Verdict

**FAIL.** Trial 4.2's exact shape is fixed and the fix is sound for it, but
`function` as a property key produces the same `return not in a function`
refusal, which is an under-wrap and would break a real script. Add the
key/member guard for the `function` token and a test for
`{ function: ... }` before a conditional return.

— signed off against `bb716fb`.
