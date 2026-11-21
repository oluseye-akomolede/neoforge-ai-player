# Review — b5a2601: the parser decides body-vs-program (F-1/F-2 on bb716fb)

- **Rev reviewed:** `b5a2601` (on `bb716fb`), branch `minecraft-wt-deepseek`,
  `~/minecraft-wt-deepseek/agent-script-runner`. Tree clean at review time
  (restored byte-identical after every mutant; sha256 verified).
- **Verdict:** **PASS** — F-1 and F-2 are closed, and by the right method:
  the hand-written scanner is deleted, not patched. Trial 4.2's shape runs, the
  over-wrap direction is unchanged, and the retry cannot execute twice.

## The fix

`#hasReturnStatement` and its function-depth track are gone. `#evalSource`
(`src/engine.js:697-704`) now:

1. compiles the source **as a program** (`evalCode(source)`);
2. returns it unchanged if it compiles or if it fails for any reason other
   than `SyntaxError: return not in a function` (`:700`);
3. retries exactly once, wrapped in `(function(){ ... })()`, only for that one
   message (`:704`).

Deleting the scanner is the correct response. It had now been wrong three
times in three different ways (the code says so at `:678-681`), and each fix
was a guess about syntax. Handing the decision to the engine removes the class
of defect rather than the instance.

## Check 1 (PASS): trial 4.2's shape and my F-1 shapes run

Driven through the real `Sandbox.evaluate` with a real limited runtime, not a
copy of the logic:

| source | result |
|---|---|
| `const ops={function:'mine'}; if(ops.function==='mine'){ return 'BODY'; }` | `OK "BODY"` |
| `const ctx={function:1}; for(const k in ctx){ return 'BODY'; }` | `OK "BODY"` |
| `const o={function:1}; { return 'BODY'; }` | `OK "BODY"` |
| `(function(){ return 7; })()` | `OK 7` |
| `(() => { return 7; })()` | `OK 7` |
| `1 + 1` | `OK 2` |

Both F-1 shapes from my `bb716fb` review now pass, and the IIFE/expression
cases the commit deliberately protects still keep their values.

## Check 2 (PASS): the retry cannot run anything twice

This is the one assumption that could be catastrophic and is invisible on
inspection, so I measured it with observable side effects inside the guest.

| probe | result | what it rules out |
|---|---|---|
| `globalThis.COUNTER=0; COUNTER++; if(1){ COUNTER++; return COUNTER; }` | `OK 2` | a program run *then* a body run would yield **3** |
| `globalThis.N=0; eval("N++"); N++; if(1){ N++; return N; }` | `OK 3` | runtime `eval` not double-applied |
| `globalThis.N=0; eval("N++"); if(1){ return N; }` | `OK 1` | eval runs once |
| `globalThis.N=0; eval("globalThis.F=function(){N++}"); F(); if(1){ return N; }` | `OK 1` | eval-defined fn called once |
| `if(1){ return 'BODY'; } throw new Error('must not run');` | `OK "BODY"` | the throwing tail never executed |
| `let x = ;` | `REFUSED: unexpected token in expression: ';'` | a non-return syntax error does **not** retry |
| `while(true){}` | `REFUSED: interrupted` (one interrupt, rc=0 within 90 s) | the old hang-twice form stays fixed |

The counter reaching exactly **2** (and **3**/**1** in the eval variants) is the
positive control that matters: a parse error executes nothing, so the program
text never ran before the retry. The builder's compile-vs-run claim is right,
and I verified it independently rather than taking the note.

## Check 3 (PASS): other errors are untouched

- `var a; let a;` → `REFUSED: invalid redefinition of global identifier` — the
  **program** wording, not a retried body's. The earlier scanner-based form
  would have reported differently here.
- A real syntax error (`const o = {;`) → `REFUSED: invalid property name`,
  reported unchanged.
- Both error objects carry `{kind, name, message}` and nothing else.

## Check 4 (PASS, with an accurate caveat): the line offset does not bite

The wrapper shifts a retried error's reported line by one. I checked whether
anything consumes a line number:

- `grep -rn "lineNumber|\.line\b|line:"` over `src/engine.js` and
  `src/binding.js` — **no hits**.
- `normaliseError` returns `{kind, name, message}` only (`src/engine.js`
  `normaliseError`), so no line survives to any caller.
- The planner side (`agent/l3_planner.py`) has no line-number reader either.

Measured: a body-path error and a program-path error with the same `throw` on
the same source line both report `script_error` / `L3` — identical output, so
the offset is not observable today. The builder's caveat is honest and
correct: if line numbers are ever surfaced, that shift becomes a real gap and
should be fixed then. Not a finding now.

## Mutants (run by me, one at a time, tree restored byte-identical each time)

| mutant | reds | intended target |
|---|---|---|
| retry on **any** `SyntaxError` (drop the message equality) | **2** | `ANY OTHER SYNTAX ERROR IS REPORTED UNCHANGED (no retry, no shift)` + a trap-provenance test |
| retry **never** happens (`return program` before the retry) | **27** | the return-value and host-call tests |
| program **always** wrapped (skip compile-first) | **94** | 8-cap/rate tests, the whole host-call surface |

Every mutant goes red and no mutation left the tree changed
(`sha256` identical before and after).

## Suites (bounded, declared command)

`node --test --test-timeout=40000 "test/*.test.mjs"` (read from
`package.json`): **179 tests, 179 pass, 0 fail, rc=0** — the builder's figure
is exact. `NODE_OPTIONS="--max-old-space-size=2048"`, `nice -n 19`.

## Notes (not findings)

- **Line offset** — see check 4; correct to defer, real if line numbers are
  ever surfaced. Worth a one-line comment at the retry site so the next reader
  knows the shift is deliberate.
- The comment at `:687-692` records the measurement (SIDE still 0) that the
  retry cannot run twice, and names the earlier hang-twice form. That is the
  right place for it.

## Verdict

**PASS.** The scanner is properly gone, the parser decides, both F-1 shapes and
trial 4.2's shape run, the retry is single-execution by measurement, other
errors are untouched, and the only caveat (the line shift) is invisible today
and honestly flagged.

— signed off against `b5a2601`.
