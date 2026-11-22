# Three changes (95b9005, 04346d6 / 0dab107, eb5498f / 63e7d92) — A and B PASS, C NOT PASS

Reviewer: minecraft-reviewer@minecraft. 2026-11-22. Answers the P6 finding at
`112343d` and the plan preconditions P3/P5.

| Change | Revs | Verdict |
|---|---|---|
| A. per-bot L3 routing | `95b9005` + `04346d6` | **PASS** |
| B. stop supersedes in-flight re-plans | `0dab107` + `eb5498f` | **PASS** |
| C. runner repin + prod manifest + token script | `63e7d92` | **NOT PASS** (C-1, C-2) |

Nothing was applied. No step was run. No secret was created or read.

---

## A. Per-bot L3 routing — PASS

All four checks the handoff asked for hold.

**The gate is one predicate at all three sites.** `planner.l3_path_enabled`
(`planner.py:306-344`) returns `(on, reason)`; `agent._l3_path_enabled`
(`agent.py:282-305`) is the single wrapper, used at `:923` (chat gate),
`:1147` (L3 acceptance) and `:5702` (order lane). Both chat sites are gated
identically, which is the thing that would have drifted.

**The legacy splice is still reachable — and that is now correct.** I re-ran the
render matrix at the rev with `psycopg2` stubbed, forcing `use_l3_plan_layer=False`
as prod has it:

```
step3 prod         l3=False offered=False legacy_surface=False l3_section=False
step3 prod other   l3=False offered=False legacy_surface=False l3_section=False
step4 Mystic       l3=True  offered=True  legacy_surface=True  l3_section=True
step4 other        l3=False offered=False legacy_surface=False l3_section=False
named, no runner   l3=True  offered=False legacy_surface=False l3_section=False
```

A bot **not** in `SCRIPT_BOTS` with the flag unset renders as prod does today:
all three surfaces empty. That is the regression check and it passes.

`step4 Mystic` still shows `legacy_surface=True`, and my F-7 asked for that
splice to be "gone or unreachable". I took the other of your two options and
looked at whether it is a problem, because a render returning True is not by
itself a defect: **Mystic is routed to L3 at `:923` before the decompose branch
at `:1147` is ever reached**, so the legacy prompt is not what that bot sees for
a chat instruction. The offer is rendered, not consumed, on the routed path.

**BUT that is conditional on a bind path I could not resolve, and it is the one
thing in A I cannot close from here.** `SCRIPT_SURFACE` and the L3
`_PLAN_SCRIPT_SECTION` teach *different dialects*. Measured by extracting every
`api.<name>(` from each:

```
L3 plan section teaches:  do, get_directive, get_snapshot, log, recall, remember, say, send
legacy surface teaches:   do, log, recall, remember, result, say, send
```

`_PLAN_SCRIPT_SECTION` teaches `api.get_snapshot()`/`api.get_directive()` and
says "Nothing else" and "Do NOT write the script here ... a separate call is
made"; `SCRIPT_SURFACE` teaches neither, teaches `api.result`, and has the model
emit the script inline under a `"script"` key in one call. The two are not
two wordings of one contract, they are two contracts. If any path renders the
legacy prompt for a bot that was routed to L3, the model is taught
`api.get_snapshot()`, which `_PLAN_SCRIPT_SECTION` itself says "does not exist,
and a call to a missing method throws and discards your whole script".

**Reachability is not offering, and the reverse also holds: not being offered
does not mean not being rendered.** Worth a spec sentence either way; I am not
blocking A on it because the routed path does not consume the legacy offer for
chat instructions.

**`_l3_path_enabled`'s Mock fallback (M5 below).** The wrapper refuses to
tuple-unpack because several tests patch the whole `planner` module. I mutated
that guard and it did red, so it is load-bearing and pinned.

## B. Stop supersedes in-flight re-plans — PASS

The live failure (07:01:40Z, scripts `0b62fe04` and `7df52ecc` bound after a
stop) is addressed at both places a superseded run can still act:
`_bind_planner_script` (`agent.py:4012-4022`) and `_resubmit_yielded_goal`
(`:4260-4270`), both reading `_goal_generation_is_stale` against
`_active_goal_generation` captured at `_run_orchestrator` entry (`:1999`).

**Mutants — four, each applied behind an `assert old in s` and AST-checked:**

| Mutant | What it removes | Result |
|---|---|---|
| M1 | the stop's advance (`_supersede_goal(...)` → `0`) | **reds 1**: `test_the_stop_path_advances_the_generation` |
| M2 | the bind guard (`if False: return False`) | **reds 1**: `test_bind_refused_when_the_generation_went_stale` |
| M3 | the re-plan guard | **reds 1**: `test_replan_does_not_start_after_a_stop` |
| M4 | `reset()`'s advance | **reds 0 in 666 tests** |

**N-1: reset's advance is unguarded by any test.** It is one word, and the
comment above it claims the same reasoning as the stop. `ResetSupersedesInFlightWorkTest`
(`test_goal_generation_stop.py:127-136`) calls `bot._supersede_goal(reason="reset")`
*directly* — so it tests the method, not that `reset()` calls it. That is the
same shape the commit message says the builder's first two attempts died of
("the tests called `_supersede_goal` directly and so a stop path that never
advanced the generation stayed green"), one method over. I ran M4 against the
full 666-test suite: the only error is the pre-existing `dashboard` one. Low
severity — the call is visibly there at `agent.py:625` — but it is the exact
pattern the commit set out to stop, so it should get the same treatment.

**Is "goto/follow do NOT advance" right? Yes.** The advance lives at
`_maybe_plan`'s nav branch (`:819`), which serves follow, goto and stop alike,
gated on `is_stop`. A goto arrives as a *new instruction* that is about to start
its own `_run_orchestrator`; if it advanced the generation, the run it just
started would capture the new generation correctly — but the bind it may later
perform belongs to that new goal, so advancing would be harmless for it and
harmful only for the stale run, which the goto has already cancelled via
`_cancel_orchestrator` (`:813`). Follow is the same: it is a directive
substitution, not a goal end. The reasoning in the comment holds. I checked the
one case that would make it wrong — an in-flight plan whose bind lands after a
goto — and the `_cancel_orchestrator` at `:813` covers it.

**Nav phrase tables moved to module scope and `is_stop_instruction`.** The
inline expression and the helper agree on every input I could construct: the
helper is `any(p in low for p in NAV_STOP_PHRASES) or any(low == p for p in
NAV_STOP_EXACT)`, matching the original's `any(... in ...) or any(... == ...)`
with the same 8 phrases and the same exact list. No behaviour change.

**Coverage of the other paths the handoff lists.** Result hand-back `:1309`
starts an orchestrator which captures the current generation at `:1999`, so it
is superseded the same way. Task-board claim and delegated peer task both run
inside `_run_orchestrator` after the capture, so they inherit it. I found no
bind or plan-set site that skips the check except `_bind_planner_script` reached
from `on_script` inside the capture window — which is the case the guard covers.

## C. Runner repin, prod manifest, token script — NOT PASS

The digest work is right. **The token script writes the wrong value.**

### C-1 (blocking): the prod secret would hold the token double-encoded

`scripts/make-prod-runner-token.sh:55-57`:

```sh
printf '%s' "$TOKEN" | kubectl -n "$NS" create secret generic "$SECRET" \
  --from-file="${KEY}=/dev/stdin" --dry-run=client -o yaml \
| kubectl apply -f -
```

Two things happen in that chain that the file's own docstring forbids:

1. `--from-file` puts the **raw 96-hex-character token** into `data.<key>`.
2. `-o yaml` then renders that `data` map **base64-encoded**, because that is
   how Secret values are serialised.
3. `kubectl apply -f -` decodes it once on ingest, so the stored value is
   **base64(96 hex chars)** — 128 characters — not the token.

I ran it against a fake `kubectl` that consumes the pipe the way the real one
does. The bytes that reach the *first* kubectl's stdin are the raw token:

```
7242ad785c5dd58c132eacfcb5b598f214814742c6474ff52f84ba815d6b5e5e4ed0559a15e8d96c197b21874febe831   (96 chars)
```

and the bytes the *second* kubectl receives are the YAML document with the
value base64-encoded under `data.`. The agent would then present a 128-character
value as its runner token and every tick would 401.

**The script cannot detect this.** Its self-check is
`[ "${#TOKEN}" -eq 96 ]` on the *pre-kubectl* variable, and its fingerprint is
computed the same way:

```sh
FP=$(printf '%s' "$TOKEN" | openssl dgst -sha256 | awk '{print $NF}')
```

so it prints a fingerprint of the value it *meant* to store, never of what it
stored. A successful-looking `created secret ... fingerprint: sha256:xxxxxxxx`
is emitted either way. This is the failure mode where the verification is of
the intention rather than the artefact.

The fix is to drop the YAML round-trip — `| kubectl apply -f -` on the output of
`kubectl create ... -o yaml` is the bug; either apply the `create` output
without a second decode (it does not exist), or write the Secret with
`--from-file` directly (`kubectl create secret generic "$SECRET" --from-file=... --dry-run=client -o yaml`
has no direct apply form that preserves raw bytes), or generate
`printf '%s' "$TOKEN" | base64 -w0` into a small `data:` manifest. Whatever is
chosen, the script must then **read the stored value back and fingerprint what
it stored**, not what it generated.

I did not determine which alternative the builder intends; the report is that
the current three lines do not store the token, and their own check cannot see
it.

Two parts of C-1 are correct and worth keeping: nothing derived from the token
reached stdout or stderr in my run (the fake's output was
`created secret ...` + `fingerprint: sha256:72333b67`); and no invocation put
the token in an argv element (the argv log shows `--from-file=minecraft=/dev/stdin`,
`apply -f -`, and the `get`). The stdin path is right; the YAML round-trip on
top of it is wrong.

### C-2 (blocking on P5): the docstring claims a guard the code does not implement

The header says:

> THE CONTRACT: nothing on stdout/stderr is derived from a print of the token.
> ... Never an argv element ... The only output is `sha256:<8 hex>`.

and twice, "do not add an --echo flag". But the script has **no `--echo` flag
and no parsing of `$@` at all** — `"$@"` is never referenced. A third party can
invoke it as `make-prod-runner-token.sh --echo` and it will simply run as
normal. The claim that the interface cannot be coaxed into printing the token
is a claim about a flag that was never written. Either implement the refusal
(`[ $# -gt 0 ] && exit` with a message) or delete the paragraph; as written the
header will be quoted into the rollout row as a guarantee.

### C-3 (non-blocking): the fingerprint disagrees between the two paths

The create path fingerprints the raw token; the already-exists path fingerprints
`kubectl ... -o jsonpath=.data.<key> | base64 -d | openssl dgst`. Under C-1
those are different values, so a re-run would print a fingerprint that does not
match the create path's. Once C-1 is fixed they agree — but that is the
signature of "the fingerprint is not of the stored bytes", and it should be
resolved by reading back rather than by keeping two computations in step.

### What in C is verified and right

- **The repin digest is the live one.** I read it myself:
  `deployment.spec...containers[0].image` and the running pod's
  `imageID` both report `sha256:1da521c1fac884bcabcf52c9d5cd5a7c3d1d9ca269f7088cd98966832fee8714`,
  and `manifests/agent-script-runner.yaml:88` at the rev carries exactly that.
  The old pin `sha256:6e079944` is gone.
- **The prod manifest is composed from the live object, not a namespace
  substitution.** Digest identical; `requests {cpu 500m, memory 4Gi}` and
  `limits {cpu 2, memory 12Gi}` match what I read from the live test
  Deployment; ports `contract:8080` / `health:8081` with `/readyz` on `health`
  match live; only `RUNNER_TOKEN_MINECRAFT` + `NODE_OPTIONS` (test also has
  `RUNNER_TOKEN_CARDGAME`, correctly dropped); secret name/key resolve to
  `agent-script-runner-token`/`minecraft`, which are exactly the live test
  secret's two keys.
- **The ingress label is real.** I read it live: ns `minecraft` pod
  `minecraft-server-7d947547d6-957t6` carries `app=minecraft-server`. Not a
  guess.
- **The prod secret does not exist yet** — I checked and got NotFound, so P5 has
  not been half-done.
- **The NetworkPolicy is documented as inert and that is correct.** kube-flannel
  accepts and enforces nothing; the file says so in its own comment and does not
  claim a boundary it does not have.
- **The "tokensFromEnv" comment correction is right.** One game key is
  startable; the prod file's single-key env is coherent with the code the digest
  pins.

## Not established

No live bot. No prod write. The runner changes were read, not applied; the token
script was exercised only against a fake `kubectl`, which is enough to show the
value it would store and not enough to show what a real `create`/`apply` pair
does with a manifest-less input — the double-encode is a property of `-o yaml`
on a Secret, not of the fake.

Suite at `04346d6` + `eb5498f`: **Ran 666, errors=1** — the one error is
`dashboard` (no uvicorn), pre-existing and unchanged from `3e900cc`'s 641-test
run. `test_goal_generation_stop`: Ran 13, OK.
