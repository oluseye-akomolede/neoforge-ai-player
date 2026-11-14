# Review: five items, `cab3768` / `3881f6c` / `2296611` + `e37945e`

Row `qitem-20261114045129-72310386b4430817`. Read from `git archive`, never a working tree.
Reviewer: minecraft-reviewer. Revs reviewed as named.

## Verdict

**PASS with one test-isolation finding (T1).** No defect found in the product code of any of
the four commits. T1 is in the test harness, is spurious-failure shaped, and does not hide a
regression.

---

## `cab3768` — precheck exits 9 when the scorer surface cannot load

Verified the mechanism at source. `planner._load_surface()` catches the `action_binding`
import failure into `_SURFACE_ERROR` and leaves `SCORERS` populated, so an import-only check
returns healthy against a broken surface. `run.py:229-234` reads `_load_surface()`'s return
and `main()` exits 9 at `:258-260` before any case is scored. `PYTHONPATH: /opt/aibot-agent`
present at `job-evals.yaml:116-117` with the reason in a comment.

**Mutation reproduced, with a caveat the builder should know.** Replacing the surface check
with `import action_binding` reddens exactly one test:
`test_run.ScorerSurfaceTests.test_an_unloadable_action_surface_is_refused`. It reddens as an
**ERROR, not a FAIL**, because the bare import raises in the harness before the assertion is
reached. The guard works; it works by exception. Worth knowing if someone later triages by
"failures" only.

My first attempt used `import agent.action_binding`, which is not how the real code imports
it, and produced 14 errors — a malformed mutant is not evidence. The second used the real
name.

## `3881f6c` — ticks tasks 1.1-1.10

All ten ticked, all ten present in the tree at that rev. These are the same behaviours I
verified at `4c33bc7` / `4d87eb9` / `6d57894`, so re-deriving them was redundant; I
spot-checked 1.1-1.3 exist at the rev rather than trusting ticks. `validate --strict` valid.

## `2296611` — three lead items

96 tests OK on my run (`discover -s agent/output_evals/tests -q`).

- **clarify/refuse no longer auto-passes.** Restoring the old `return Result(PASS, ...)`
  reddens exactly three tests and leaves the clean-plan test green — counting, not a blanket
  red. `declined` is a `defaultdict` rendered `dict(sorted(...))` at `run.py:155`, built at
  the top level of `run()`, so it is present-and-empty rather than absent.
- **`score_replan` now loads the surface** and runs `check_kind_surface` over directives.
- **`x-agent-image` anchor removed**, digest inlined at both sites. Safe-loads as one doc.

## `e37945e` — gateway passes `think` through

One file, both request models (`ChatRequest:89`, `_OllamaShimChatRequest:391`), outbound body
at `:319-320`, shim forward at `:409`. Parent's body construction had no `think` key, so the
silent drop was real. Omitted when `None`, not sent as `false` — existing callers byte for
byte unchanged.

**Queued path checked, since it could drop the field a second time:** `QueuedRequest.payload`
is typed `ChatRequest` and `_process` reads `item.payload`, so the whole object (including
`think`) survives the queue. No second drop.

**Not run by me:** pydantic is absent from this VM, so I could not instantiate the models to
watch validation. I verified the declaration and the outbound logic by reading the exact lines
above. A live `curl` through the shim is the check I could not do here; the builder tested the
upstream model directly, which is a different hop.

---

## T1 — `test_run.py` has a cross-test isolation defect (new finding)

**Observed:** the same commit (`cab3768`) gives different results depending on invocation:

| invocation | result |
|---|---|
| `python3 -m unittest discover -s agent/output_evals/tests -q` | **90 OK** |
| `python3 -m unittest discover -t .` (from repo root) | fails |
| `python3 -m unittest test_run` (single module, cwd=tests) | fails |

**Characterised, not root-caused.** With the tests' own `sys.path` shim in place, discovery
passes (`FAILURES: []`). Without it, `ScorerSurfaceTests` fails its unloadable-surface
assertion while passing in isolation — i.e. state left by an earlier test changes the result.
`RunnerTests` precedes it; any single `RunnerTests` test reproduces the poisoning, which points
at `test_run.py`'s module-level path insertion rather than one test body.

**Severity: low, and bounded.** I checked the direction that matters — the guard is **not
inert**. It reddens on a real regression under the builder's own invocation (`-s ... -q`).
So this is a spurious *failure* under some invocation styles, not a spurious *pass*. It cannot
let a broken precheck ship.

**Why I stopped:** I spent five reproduction attempts without isolating the root cause, and my
emulations kept passing while the runner failed. The reproducible fact is solid; the mechanism
is not, and I am labelling it as such rather than guessing a sixth time. Fix suggestion, not a
requirement: clear `sys.modules` of `action_binding` and `agent.*` in `setUp` so per-test
isolation does not depend on import order.

---

## Item (5) — images

Agent + gateway image builds wait on a PASS. **This is that PASS,** with T1 recorded as a
non-blocking test-harness finding. Rollback and verification to be recorded on the row that
authorises the build.

## Reviewer's own errors this round

- Malformed first mutant (`import agent.action_binding`) — wrong import form, 14 errors, not
  evidence. Re-run with the real name.
- `git rev-parse --short A B C` rejected; looped instead.
- T1 root cause attempted five times without success; recorded as characterised, not solved.
