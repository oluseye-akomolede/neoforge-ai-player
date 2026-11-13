# Review — ROTATION-PLAN-RUNNER-TOKEN.md at `31f166d`

Reviewer: minecraft-reviewer@minecraft. 2026-11-13 ~11:20Z.
Row: `qitem-20261113110946-1b676f5be3694dd6`.
**Verdict: PASS, with two corrections that must be applied before the lead runs it.**

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

## Live-state drift the lead should know before running

- `aibot-agent-test` is **not paused** now (`spec.paused` empty). Step 4's pod-delete
  branch is therefore not needed today; `rollout restart` is available. The plan handles
  this correctly by re-reading at run time — this is just the current value.
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
