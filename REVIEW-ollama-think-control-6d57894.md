# Review — `openspec/changes/ollama-think-control/` at `6d57894`

Reviewer: `minecraft-reviewer@minecraft`. Row `qitem-20261113194852-b6c380519c5e72d6`.
Supersedes `REVIEW-ollama-think-control-f0a6a41.md` (commit `3b7313a`).
Read from `git archive 6d57894` into `/tmp/rev-6d57894` — not from a working tree.

## Verdict: PASS, with two nit-level notes that do not block code

N1 is closed correctly and completely. The dangerous part of the change — a
think-on leg that quietly measures think-off — is now specified end to end:
generator writes the key, loader type-checks it, the probe keys on the resolved
value, and a report that omits the value is no longer possible to miss.

I verified the premise behind task 1.9 rather than taking it, because if it were
false the type check would be ceremony. It is true. Details below.

## The two notes (neither blocks; fix when convenient)

### Note 1 — `bool()` is the wrong check, and the change would permit it

Task `1.9` says "accept only a real bool (or the YAML booleans)". Measured with
PyYAML 6.0.1:

| file text | `safe_load` gives |
|---|---|
| `think: false` | `False` (bool) |
| `think: "false"` | `'false'` (str) |
| `think: 1` | `1` (**int**) |

An implementation written as `merged["think"] = bool(merged["think"])` —
`bool` is the obvious reading of "type-check it as a boolean" — accepts
`think: 1` silently. Measured: `bool(1)` → `True`. That fails loudly-wrong on a
file whose author wrote an integer.

The check that matches the scenarios is `isinstance(merged["think"], bool)` —
exact, no coercion — with `think: 1` refused by the same error as
`think: "false"`. Note the existing loader does not help here: the
`endpoint`/`model` check is `isinstance(..., str)`, which would *reject* the
bare `true` if the literal `YAML bool accepted` idiom were copied. My earlier
review said the loader "type-checks the other four" — that is true of the intent
but the `timeout`/`concurrency` check is a coercing `int(...)` inside a
`try/except`, so it is not a drop-in model for a key where coercion is exactly
the bug.

**Suggest**: change 1.9's wording from "a real bool (or the YAML booleans)" to
`isinstance(x, bool)`, and add `think: 1` to task 1.10's cases.

### Note 2 — `think` must be added to both report sites, not just one

The report does not carry this provenance by accident; both report-builders
list config fields explicitly:

- `run.py:145-148` — `build_report`,
- `run.py:254-256` — the dry-run path.

Adding `think` and its provenance to only `build_report` leaves a dry run, which
the lead will very plausibly use to check a config before spending 75 cases,
silently reporting no `think` at all. Task 1.10's "the report says 'default'"
does not say *which* report. Small, but it is the same class as the finding I
filed: a value that exists and is not visible where it is read.

**Suggest**: name both `run.py` report sites in task 1.10.

## Closed

**N1 — closed.** All four pieces present at `6d57894`:

1. `proposal.md:78-84` names `make-evals-configmap.sh:70-77` in "Affected code"
   and says why.
2. `proposal.md:85-87` and task `1.9` add the typed bool check, with the reason
   stated in the artifact ("a YAML `think: "false"` is a truthy string").
3. Scenario "An omitted key takes the default and says so" (`spec.md:56-63`)
   records provenance "the way `endpoint_from_env` already records endpoint
   provenance" — and that citation is accurate: `evalconfig.py:71-77` sets
   `endpoint_from_env` and `run.py:147`/`:257` emit it into the report. The
   precedent exists; check item Note 2 for the consequence.
4. Task `1.7` and the think-on scenario now both key on the **resolved** value:
   "the probe fires on the resolved value being `true`, whether that value came
   from the file or from the default". That closes the ambiguity I raised
   (probe on `think == true` vs on a key being present) in both places it could
   have been read.

Task `1.10` tests all three cases the scenarios describe, and "the report says
'default'" is the right assertion shape — it tests what a reader sees rather
than what a variable holds.

## The premise, measured

`agent/output_evals/evalconfig.py:66` is
`merged.update({k: v for k, v in raw.items() if v is not None})` — **every** key
in the YAML reaches `merged` unfiltered. So a `think: "false"` string does
arrive at the check, and the check is load-bearing. Confirmed.

One thing the task's wording implies that I have to correct: an unknown key is
**not** silently dropped today. `evalconfig.py:92-94` builds `Config` with
positional arguments, not `Config(**merged)`, so an unrecognised `think` key
never reaches the constructor at all — it sits in `merged`, is never read, and
is discarded with no error. Measured in the same batch: `Config(**merged)` with
an extra key raises `TypeError: unexpected keyword argument`, so the drop is a
consequence of the positional call, not of the dataclass.

The practical effect is the same (the key is admitted untyped and unread, which
is the silent-success shape in the finding), but the *mechanism* differs: there
is no error being swallowed, so a fix that adds `think` to the dataclass without
the type check would now be the only thing admitting it, and the string case
would then reach `think` as a truthy `str` with nothing between it and the
request body. The new scenario closes that.

## Unchanged and still correct

Everything I passed or noted at `03ff511`/`f0a6a41` and that this delta does not
touch: top-level `think`, explicit-not-omit, the `length` predicate, the
`("true","1","yes")` agent idiom, the eleven `message.content` readers as local
edits, the test/prod split, the 14-site inventory and the 6-file gateway
inventory.

## Instruments

- `git archive 6d57894` → `/tmp/rev-6d57894`; `diff -u` against
  `/tmp/rev-f0a6a41` for all three files. The delta is additive in every file:
  no existing requirement, scenario or task was removed or weakened.
- `openspec validate ollama-think-control --strict` in a clean archive at
  `/tmp/scratch-validate2` → *"Change 'ollama-think-control' is valid"*, rc 0.
  Run in a tree that holds the rev, after the `f0a6a41` round where I first ran
  it in the wrong worktree and got "Unknown item".
- YAML typing measured directly: `yaml.safe_load` on seven scalar forms under
  `python3 -I`, PyYAML 6.0.1. `bool(1)` measured separately → `True`.
- Loader behaviour read at `evalconfig.py:60-94`: the `merged.update` line, the
  two type-check blocks, the `endpoint_from_env` provenance, and the `Config`
  constructor call — which is positional at `:92-94`, not `Config(**merged)`.
  A `Config(**merged)` with an extra key was executed and raises `TypeError`;
  I had assumed otherwise and corrected the paragraph above after running it.
- Not run: no test suite (none covers `output_evals` for `think` yet), no
  cluster command, no gateway command. This is a spec review; every claim is
  about file contents at `6d57894` or about a Python expression I executed
  locally.

## Scope check for the code task

When code starts, `1.2` lists four modules and `1.3` says "thirteen copies".
Both are consistent with the 14-site inventory (13 agent + `run.py:54`), which
`1.5` covers. No count drift since `f0a6a41`.
