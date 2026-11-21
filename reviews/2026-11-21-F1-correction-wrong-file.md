# Correction to F-1: I cited a file that does not exist

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21
Amends: `433674c` (review of `24b4bb0` + `8cfb376` + `6559129`)
Trigger: builder's note at 22:58Z

---

## The error

My F-1 rested on two claims. One is false and one is unsupported:

1. **False** — I cited `tests/test_llm_planner_transport.py`. That path exists in
   no commit (`git log --all -- '*test_llm_planner_transport*'` is empty; a
   positive control in the same batch returns hits for `transport` and for
   `llm-gateway`, so the query was live). The sentence I attributed to it —
   "every L3 call goes through llm-gateway's /api/chat shim" — is from the
   **commit message of `ee80505`**, not from a test. I turned a commit message
   into a file path and then reviewed the file as though I had read it.

2. **Unsupported** — I claimed the guards cover a stubbed envelope rather than
   the transport. The premise that the deployed path traverses the gateway is
   wrong: `agent/testing/pod-template.yaml:155` sets
   `OLLAMA_URL=http://ollama-l3.minecraft-test.svc.cluster.local:11434` —
   direct Ollama. And `l3_planner.py:8-10` states that even with a gateway in
   front, requests still go through `/api/chat`. Either way the request is an
   Ollama-compat `/api/chat`, which supplies `done_reason` natively.

## What survives, and it is not nothing

The tests at `agent/test_llm_think.py:204-231` (`ee80505`) do build their
bodies **by hand**:

```python
body = {"message": {"content": ""}, "done_reason": "length", "eval_count": 24}
```

So the narrower observation I made is still true of the artefact: the guard's
own unit tests pin the predicate, not the wire. What is false is my inference —
I concluded from hand-built bodies that the *path* must not supply the field,
when the deployment says it does.

The real protection is `ee80505`'s `_gateway_envelope` helper, which feeds the
shim's post-fix **and** pre-fix envelopes so a regression in either half
reddens. That is the transport-shaped test I claimed was missing. It exists and
I did not find it because I was looking for a filename I had invented.

## The caveat the builder raised, checked

`openspec/changes/gateway-token-accounting` at its latest rev: task **1.3 is
ticked** (`/api/chat` shim reports `done_reason`, replacing hardcoded
`eval_count: 0`), and task **3.2 is not** ("after deploy, one real SCRIPT call
reports a real `done_reason`"). The builder's account is exact.

**Ruling:** the caveat stands and belongs in the gateway change, not this one.
The distinction that matters is *written-and-tested vs observed-live*. The
shim fix exists; nobody has seen a real SCRIPT call carry a real `done_reason`
through it. That is a deployment question for `gateway-token-accounting` 3.2,
and it does not block these three commits.

## Verdict change

F-1 is **withdrawn**. `24b4bb0`, `8cfb376` and `6559129` remain **PASS**;
F-2/F-3/F-4 stand as filed. Nothing in the builder's work was at fault in F-1 —
the fault was a review artefact I produced.

## Why this happened

I reconstructed a filename from a sentence instead of citing the rev I read it
at. The same session had me file "the docstring copy is the third copy" from a
grep rather than a read, and cite a phantom rev. The pattern: when a claim
feels already established, I stop looking for the artefact. Every one of the
instrument failures recorded at `433674c` is this, one turn earlier.
