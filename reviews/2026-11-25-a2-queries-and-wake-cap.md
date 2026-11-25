# Review — A2: script-declared queries + planner wake-cap removal

**Row:** `qitem-20261125043633-8683cec2ec0065e3`
**Requested by:** minecraft-builder (queue handoff), lead's A2.
**Verdict:** **PASS WITH FINDINGS** — ship-able; one finding is a spec'd safety
property that the shipped parser does not enforce. Not a blocker by the lead's
scope, but it should not be called done silently.

Revs reviewed (all resolve; read from a clean `git archive`, not the builder's tree):

| Rev | What |
|---|---|
| `400af67` | spec: wake caps removed |
| `e89e22f` | spec: script-declared queries |
| `389a658` | code: cap/cooldown deletion |
| `9ce7018` | code: declared queries (542-line parser + tests) |
| `51d3b08` | tasks ticks 7.1–7.5b, 7.6 open |
| `b1cd6f5` | agent-script-runner: `look.queries` |

---

## Requirement A — planner wake cap removal: **PASS**

- **Spec.** The hourly cap and 15-minute cooldown are *removed and stated as
  removed*, not silently dropped: `spec.md:356-364` gives the owner decision
  (A2, 2026-11-25 00:59Z) with its rationale, and replaces the three cap
  scenarios with "serialisation, not a rate: a failure result MUST consume the
  same ONE in-flight planner slot as any other result-triggered call, and a
  result that arrives while a call is in flight MUST stay pending rather than be
  dropped." That is a requirement for the surviving mechanism, not a hole.
- **Code.** `389a658` deletes `MAX_RESULTS_PER_HOUR`, `COOLDOWN_SECONDS`,
  `HOUR_SECONDS`, the clock and the call history; `ResultSlot` keeps one pending
  result and refuses only on identity. The `agent.py` hunk is six lines and
  removes the dead `held (hour-cap/cooldown)` branch.
- **The in-flight guard survives.** `agent/agent.py:1304` (`if self._plan_steps:`)
  is untouched — verified by diff, not by reading the message.
- **The standing-orders cooldown survives.** `cooldown_until` at
  `agent/agent.py:5316` and its five live sites are untouched; the only
  `cooldown` line changed in the diff is the deleted branch's own log line.
  Requirement A's "different, sid-keyed mechanism; deleting it is a regression"
  is satisfied — it was not touched.
- The retired-cap tests are **removed with the behaviour, not skipped**, and
  replaced by positive tests that consecutive results each reach the planner.
  Checked: the removed tests are gone from the module, not `@skip`ped.

## Requirement B — declared queries: code is careful, one safety gap

The parser (`agent/script_tick.py:114-264`) is a strict literal scan, not
`ast.parse` and not `eval` — the two failure modes the docstring names are real
and the comments explaining them are accurate. It enforces: bare binding only
(not `x.queries`), at most one declaration, object literals only, a key
allow-list (`__proto__` refused there), duplicate-name refusal, and a count cap.
All of that is correct as written.

### F-1 — `; evil()` is accepted where `+ evil()` is refused. **The spec's own hostility case survives with a terminator.**

The rule at `script_tick.py:259-263`:

```python
rest = _skip_ws_and_comments(source, m + 1)
if rest < n and source[rest] not in ";\n":
    raise DeclaredQueriesError(...)
```

`rest` is advanced past whitespace *and comments*, then the check accepts `;`
or `\n` immediately after the closing `]`. But accepting `;` and then **stopping
the check** means everything after the `;` is unexamined. Measured on the shipped
module (`/tmp/a2-agent/agent`, `parse_declared_queries`):

| Source | Result |
|---|---|
| `queries = [...]; evil()` | **ACCEPTED** — binds, and `evil()` runs when the script runs |
| `queries = [...];` (end) | accepted |
| `queries = [...];\napi.log(1)` | accepted |
| `queries = [...] + evil()` | refused |
| `queries = [...], evil()` | refused |

The script source is executed by the runner service (`script_tick.py:18`), so a
`;`-separated `evil()` executes exactly like the `+`-separated one the spec
names. `spec.md:186-190` states the rule and its reason: "*nothing MAY follow
the closing `]` on its statement except a terminator or comment* (`queries =
[...literal...] + evil()` otherwise parses as the array while `+ evil()` still
executes when the script runs — validation that gives false assurance)." The
requirement's *purpose* is to stop validation from giving false assurance;
`; evil()` gives exactly that, and the shipped code accepts it.

**Is it a defect against the requirement as written?** Two readings:
- *Literal.* "on its statement" — a `;` ends the statement, so `evil()` is a
  separate statement the rule does not cover. Under this reading the code is
  conformant and the spec is under-specified.
- *Intent (which the spec states explicitly).* The rule exists because
  validation that lets trailing code run gives false assurance. `; evil()` is
  that. Under this reading the code fails the requirement.

I read it as the second: the spec gives its reason inline, and the reason is
met by `; evil()`. **This is the finding the builder should decide on**, not
something I will silently pass. A conforming fix is small: after accepting a
`;`, continue `_skip_ws_and_comments` and require either end-of-source or a
newline that terminates the statement, accepting `; <trivia>` and `; <newline>`
only. It must keep the legitimate `];\napi.log(1)` case that
`test_a_full_declaration` pins (I confirmed that test's input; it is
`];` followed by a statement, so the fix must not reject it).

### F-2 — a comment before code is refused; a comment at end is accepted. Minor, inconsistent with the spec wording.

`_skip_ws_and_comments` skips a `//` comment **and the newline after it**
(`script_tick.py:171-173`), so for `queries = [...] // hi\napi.log(1)` the
`rest` lands on `api`, not on the newline, and the tail check refuses. But
`queries = [...] // hi` at end-of-source is accepted. The requirement says
"terminator **or comment**"; a comment followed by more source is refused while
the same comment at EOF is accepted, which is a narrower rule than the words.
Low severity — it fails *closed* (refuses a valid script rather than accepting
an invalid one), so it costs a valid script a bind, not the safety property.
Worth aligning with F-1 in the same fix pass.

---

## Tests — reproduced, not accepted

- **Agent.** The builder's "227 OK from agent/" is a set I could not reproduce
  as one figure: the modules they likely mean run green individually but a full
  `unittest discover` over all 26 modules in one process reports **742 tests,
  30 failures, 1 error, 1 skip** — and **the identical 30/1/1 at the parent rev
  `389a658^`** (727 tests). So the mass failure is a pre-existing cross-module
  contamination in single-process discovery, not introduced by A2. Run the way
  the builder runs them (per-module), the eight affected modules total **294 OK,
  0 failures**: `test_declared_queries` 30, `test_script_planner_parity` 5,
  `test_agent_script_branch` 126, `test_result_delivery` 5, `test_action_binding`
  34, `test_script_tick` 66, `test_code_time` 8, `test_script_report` 20. I did
  not chase the 227-vs-294 gap; both are green and the discrepancy is set
  composition, not a red.
- **Runner.** `node --test` at `b1cd6f5`: **221/221 pass, 0 fail**, matching the
  claim.
- **Mutant (F-1 coverage).** Loosening the tail check to accept anything reddens
  exactly **1** test (the `+ evil()` case) — which is why the `; evil()` gap
  survives: nothing exercises it. Removing `;` from the accept set reddens 7
  tests (normal declarations end in `;`), confirming semicolons are load-bearing
  and the gap is specifically code *after* the `;`.
- `openspec validate --strict`: valid at the reviewed rev.

## Known open item (agreed, non-blocking)

Task 7.6 (time `findBlocks` radius 32/48 on a live server) is unticked, so the
7.2/7.3 scan bounds are provisional. Agreed: not a blocker for this row.

## What I did not do

No live bot, no deployed change, no cluster touched. Reviews read from clean
`git archive` extractions of each rev. The runner rev lives in a different repo
(`~/minecraft/agent-script-runner`, shared objects) and was tested by sha.

## Repro

```
mkdir -p /tmp/a2-agent && git archive 9ce7018 | tar -x -C /tmp/a2-agent
cd /tmp/a2-agent/agent
python3 -m unittest test_declared_queries test_script_tick   # green per-module
python3 -c 'import script_tick as st; Q="[{ \"name\": \"o\", \"kind\": \"block_at\", \"x\": 1, \"y\": 2, \"z\": 3 }]";
print(st.parse_declared_queries("const queries = "+Q+"; evil()"))'   # ACCEPTS
```
