# Review — M2 plan `9c09db6` (loader citation corrected)

**Reviewer:** minecraft-reviewer@minecraft
**Rev:** `9c09db6` (`9c09db60712af61d57ff408d8269a08d8398f892`), parent `bededde`
**Verdict:** **PASS**. No open items.

## 1. The defect is fixed, and the stronger argument is now in the plan

`:556-561` replaces the dead citation with the live loader and states the
improvement that came out of checking call sites rather than the function:

> The live loader is `load_profiles()` (`agent.py:3186`), called at `:4244` inside
> `run()`, which reads **every** JSON file in `agent/profiles/` ...
> Because the loader globs the directory, **adding keys to `scout.json` needs no
> loader change at all**

Correct, and it is a better the plan than the one it replaces: the mechanism is
now "one file changes, zero code changes to the loader, one consumer learns two
keys" instead of a claim resting on a function that never runs.

## 2. Their sweep claims verified

- `load_profile` in the plan: **one** reference, `:556`, now the correct plural.
  Matches their report.
- `PROFILE_PATH`: **one** reference, `:551`, in the sentence "`MOD_API_URL`
  (`:7`), `PROFILE_PATH` (`:87`) and the rest are read once, process-wide". That
  is a true and *different* use — evidence that env is process-wide, not a claim
  about the per-bot loader. Correctly survives. I confirm both halves.
- `config.py:7` and `:87` both resolve to the lines cited.

## 3. Citations checked

| Citation | Resolves to |
|---|---|
| `agent.py:3186` | `def load_profiles():` |
| `agent.py:4244` | `profiles = load_profiles()` |
| `agent.py:155` | `BotRunner.__init__` docstring / signature |
| `config.py:7` | `MOD_API_URL = os.getenv(...)` |
| `config.py:87` | `PROFILE_PATH = os.getenv(...)` |

## 4. Validation

`openspec validate coded-agents --strict` → **"Change 'coded-agents' is valid"**,
rc=0, run at `9c09db60712af61d57ff408d8269a08d8398f892` (rev printed by
`git rev-parse HEAD` in the same command, per their stated discipline).

## 5. Note on the defect class, worth keeping

The original citation was not wrong about existence — `config.load_profile()`
really is at `config.py:111`. It was wrong about *use*. A review that checks
"does the thing you cite exist" passes it; only checking call sites catches it.
Worth adding to checklist discipline for this repo: a cited function is verified
when its **call sites** are shown, not its definition.

## 6. Scope

Plan-only commit. Nothing ran, no probe taken. I did not re-read all 539 lines —
§7's file list and §8's proof remain untested until step 2 executes. Cluster
facts remain the builder's reads; no `kubectl` or kubeconfig in this seat.
