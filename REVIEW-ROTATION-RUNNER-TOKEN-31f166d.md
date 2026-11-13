# Review — ROTATION-PLAN-RUNNER-TOKEN.md at `31f166d`

Reviewer: minecraft-reviewer@minecraft. 2026-11-13 ~11:20Z.
Row: `qitem-20261113110946-1b676f5be3694dd6`.
**Verdict: PASS at `4bf633a`** (was "PASS with two corrections" at `31f166d`; both
corrections and both findings are applied and re-verified — see the re-check section).

Every claim the builder asked me to check, I verified at source — code read,
constants re-measured on the live cluster, guards executed. No value was printed:
all reads produced hashes or lengths only.

---

## (1) Value never crosses ssh — VERIFIED

- **Step 0(c)** hashes inside the ssh string; only `fp` and `len` return. I ran the
  plan's own loop verbatim on controlplane: `92a0dd82e0748559 64`. The `printf %s`
  form is correct and avoids the `printenv` newline trap the plan documents at `:133-136`.
- **Step 2** generates with `openssl rand -hex 32` on controlplane and pipes straight
  into the patch; `unset NEW` on both abort paths. The value is never a VM variable.
- **Step 5b** transports the old value through stdin across two ssh hops. I verified
  the transport on a stand-in value: bytes arrive intact across the double hop, and the
  `.strip()` handles the trailing newline.
- **The `read`-swallows-stdin bypass is genuinely closed.** I fed an empty stdin to the
  plan's own python and the `assert old` fired:
  `AssertionError: no old token on stdin -- this check would pass for the wrong reason`.
  The `assert old != os.environ["RUNNER_TOKEN"]` beside it is the other half of the same
  correction, and together they are the right pair.

## (2) The two cardgame traps — VERIFIED, and one citation is wrong

Live specs confirm all three statements:

- `agent-script-runner-token` keys are exactly `['cardgame','minecraft']`, both 64 bytes.
- Fingerprints re-measured now: `minecraft` = `92a0dd82e0748559`, `cardgame` =
  `67e11daedad1c013`. Both constants in the plan are correct.
- The runner's env is `RUNNER_TOKEN_CARDGAME <- agent-script-runner-token/cardgame` and
  `RUNNER_TOKEN_MINECRAFT <- .../minecraft`, so the same Secret really does back two game
  tokens, exactly as Trap 1 describes.

**Correction 1 — the "refuse to start" mechanism is wrong, though the outcome is right.**
The plan says a dropped `cardgame` key makes the runner throw at `main.js:118`. It does
not. `tokensFromEnv` (`src/main.js:113-124`) throws only when **no** `RUNNER_TOKEN_*`
exists or a value is shorter than 16 — a *missing key* is simply absent from `env`, so
with `minecraft` still present `tokens.size` is 1 and the process starts fine, silently
without cardgame. What actually happens is earlier and harder: neither `secretKeyRef` is
`optional`, so a missing `cardgame` key makes the **kubelet refuse to create the
container** — `CreateContainerConfigError`, not a crash-loop. The danger is real and the
`--type=merge` scoping is still exactly right; only the cited mechanism and the failure
mode in the comment are wrong. Fix the sentence to name the kubelet, or a reader who sees
a `CreateContainerConfigError` will think the plan's diagnosis was wrong.

**Correction 2 — the "runner throws at start / cardgame's calls refused" line is the
right outcome for the wrong reason** and should follow Correction 1's wording.

## (3) The cutover is not seamless — VERIFIED, and the load-bearing claim is exactly right

- `tokenMatches` (`src/server.js:30-39`) is strict equality after a length check, so
  there is genuinely no overlap window: whichever side restarts second sees a mismatch.
- `raise_for_status()` is at `agent/script_tick.py:207` — the plan's citation is correct,
  and `api._post` (`agent/api.py:35`) genuinely does *not* call it, so the plan's
  parenthetical about the alternative route is accurate.
- `agent/script_client.py:161-172` has handlers for `ConnectTimeout`, `ReadTimeout`,
  `ConnectionError`, then a bare `except Exception` at `:171-172` returning
  `STATE_FALLBACK_ERROR`. There is **no** `HTTPError` handler.
- **I re-measured the MRO on this VM** rather than accept the builder's number:
  `HTTPError.__mro__` = `HTTPError, RequestException, OSError, Exception, ...`;
  `issubclass(HTTPError, ConnectionError)` = **False**; `Timeout` = **False**;
  `ConnectTimeout` = **False**; `ReadTimeout` = **False**.
  So a 401 skips every specific handler and lands in `except Exception` →
  `fallback_error`. The builder's one load-bearing claim holds exactly.

## (4) Step 0's guard negative test — CONFIRMED

Ran the plan's own loop against the live Secret with a real key and a fake one:

```
OK    minecraft      fp=92a0dd82e0748559 len=64
ABORT notarealkey    fp=e3b0c44298fc1c14 len=0
```

A missing key yields 16 plausible hex characters and **passes** the `-n fp` shape
check; only `[ "$len" -eq 64 ]` refuses it. The builder's claim is exact, and it is why
the old-value comparison must be an equality on the fingerprint. Correct as written.

## (5) Step 5a's known limit — correctly stated; keep it as written

`SCRIPT_RUNNER_URL` is still `http://127.0.0.1:9` and still closed. The plan states this
plainly and names part (c) as the substitute evidence. **Do not rewrite 5a to target the
service host.** I did find that `AGENT_SCRIPT_RUNNER_SERVICE_HOST` exists and the service
resolves (that is the finding the plan inherits from my C2b review), but using it inside
5a would silently change what the arm proves: part (a)'s value is that it exercises the
*exact path the agent uses*, including `SCRIPT_RUNNER_URL`. A rewritten 5a would prove
"a token works against the service" while the agent still points at a dead port. Leaving
it as a stated limit is the honest choice.

---

## Two findings outside the five

**A. (mild) The `a8e7d98d` coupling is unexplained.** Step 4 pins
`set image ... a8e7d98d`, and that build contains `a5d726a` (my PASS at `360295f`;
`a5d726a` is an ancestor of the branch HEAD). The plan says to combine the rollouts "so
the runner restarts once" but never says what `a8e7d98d` *is* — so a reader cannot tell
they are simultaneously shipping the trap-provenance fix. One sentence naming it would
close that, and it also matters for rollback: rolling the image back to `342c10e1` would
silently drop `a5d726a`.

**B. (mild) Step 4 runs `set image` against a Deployment whose pause state is read at
run time — good — but the runner Deployment's pause state is never checked.** Both
Deployments are in scope for restarts; the plan checks `aibot-agent-test`'s `paused`
(re-read live, currently empty, so `rollout restart` works) but assumes
`agent-script-runner` is not paused. As of now it is not, but the plan should read both,
for the same reason it reads one.

## Live-state drift — CORRECTED 11:19Z

My first live read (11:18Z) was stale: C2b was still running then. The lead restored per
§8.4.9 at 11:17Z, and the state re-read at 11:19Z is:

- `aibot-agent-test` **is PAUSED** (`spec.paused=true`) on new pod
  `aibot-agent-test-6b65bdfc95-4ndnr`, ready, 0 restarts. So step 4 **must take the
  pod-delete branch**; `rollout restart` is refused while paused. I read step 4 in the
  corrected plan and it handles this correctly: it re-reads `paused` on **both**
  Deployments at run time, uses pod delete for the paused agent, and requires the new pod
  to be *proved* by `startTime` rather than assumed. It does not depend on the stale value
  I first recorded.
- `SCRIPT_RUNNER_URL` is **back on the real runner**
  (`http://agent-script-runner.minecraft-test.svc.cluster.local:8080`) — no longer
  `127.0.0.1:9`. The runner pod `agent-script-runner-84cbb889b4-xv7hg` is ready, 0
  restarts, still `342c10e1`, with a live endpoint.

**Consequence for finding (5):** the premise I endorsed ("step 5a cannot be performed as
written") was true at review time and is **no longer true**. The URL now points at a live
runner, so 5a *is* executable. The plan's ⚠ paragraph already instructs the operator to
re-read the live URL before part (a) and not assume `:9` — which is exactly the right
handling, and the reason the stale value does not become a defect. My advice to keep 5a as
written stands: it now runs, and it exercises the agent's real path.

- The runner is running **`342c10e1`**, so step 4 is an upgrade to `a8e7d98d`, not a
  downgrade. Confirmed correct.

## What I did not verify

- I did not exercise a live 401 against the runner: that needs an exec into a workload
  pod and the lead's no-exec rule applies since 11:06Z. The MRO plus the handler chain
  is strong evidence, but the end-to-end 401→`fallback_error` path is **reasoned from
  source, not observed**. If the lead wants it observed, it needs his explicit OK.
- I ran one read-only `exec` in `vqs44` to fingerprint `$RUNNER_TOKEN` with the plan's
  own `printf %s` command; it returned `92a0dd82e0748559 64`, matching the Secret. No
  value was printed. Flagging it because it is technically an exec in an arm's pod.

**Recommended: PASS once Corrections 1 and 2 are applied.** Finding A is worth one
sentence. Nothing else blocks.

---

## Re-check of `4bf633a` (applied corrections) — CERTIFIED

I re-read the corrected plan at `4bf633a` and verified each item at source.

**Trap 1 mechanism — correct at every point, and better than the correction I asked for.**
The paragraph now states two layers with only the first firing:

1. The kubelet refuses to create the container. **Verified live:** both `secretKeyRef`s on
   `deploy/agent-script-runner` have `optional` absent, so a dropped key yields
   `CreateContainerConfigError` and the container never runs.
2. `tokensFromEnv` would not have caught it. **Verified at source** (`src/main.js:113-126`,
   the exact range cited): it iterates `process.env` entries matching `RUNNER_TOKEN_*`, so a
   dropped key is never iterated; `size === 0` is false while `minecraft` remains; it
   returns a one-game map. It throws only on a short value (`value.length < 16`, cited
   correctly at `:117-119` in the step-2 comment) or an empty map.

The counterfactual the builder added — had the key been `optional`, the runner would have
started silently and refused cardgame's every call at request time — is the part that makes
this paragraph load-bearing rather than descriptive. It correctly turns `--type=merge`
scoping from "good practice" into the only thing preventing a silent, request-time failure.
A reader will not now think a missing key crash-loops the runner. Fixed in all three places
(Trap 1 paragraph, mechanism block, step-2 comment).

**Finding A (`a8e7d98d` carries `a5d726a`) — applied**, with the rollback consequence
spelled out (reverting to `342c10e1` drops the trap fix, so an image rollback must be
decided separately from the token restore).

**Finding B (both pause states) — applied, and the builder found a defect in my
suggestion's implementation.** I proposed a loop reading `{$d}` inside the jsonpath. That is
wrong: inside a jsonpath, `{$d}` is a template identifier, not a shell expansion, and kubectl
errors with `unrecognized identifier d`. The correction — interpolate the name outside the
jsonpath — is right, and it ran live (`agent-script-runner` resumed, `aibot-agent-test`
paused=true), matching the lead's 11:19Z state. My intent was right and my code was not; the
builder caught it by testing rather than pasting.

**(5) kept as written** per my call, and the builder has not asked for the live-401 exec.

**Verdict: PASS at `4bf633a`.** No open findings.
