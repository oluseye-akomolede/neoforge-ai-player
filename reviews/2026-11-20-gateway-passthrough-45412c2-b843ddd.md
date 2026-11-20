# Review: gateway token accounting passthrough

**Revs:** spec `45412c2` (neoforge-ai-player, delta `gateway-token-accounting`) +
code `b843ddd` (llm-gateway, branch `gateway-token-accounting`)
**Verdict:** **PASS** — all five checks executed. One non-blocking note (N-1).

Nothing deployed by this review; the lead builds and applies.

---

## The cross-repo seam — the thing neither suite covers

The change only matters if the gateway's envelope reaches the agent's guard. The
gateway tests stop at the envelope; `agent/test_llm_think.py` feeds `answer_text`
a hand-built body. Nobody tested the join, so I did: drive the **real** `/api/chat`
shim against a faked upstream, take its returned envelope, pass it straight into
the agent's `answer_text` at this rev.

| Upstream shape | Envelope out | `answer_text` |
|---|---|---|
| `done_reason=length`, content `""` | `done_reason: length`, `eval_count: 10` | **raises `TruncatedAnswer`** ✅ |
| `done_reason=stop`, content `""` | `done_reason: stop` | returns `""`, no raise ✅ |
| no `done_reason` key at all | `done_reason: None` | returns `""`, no raise ✅ |

All three of the spec's scenarios for requirement 2 hold through the deployed
transport, not just against fixtures. Before this change the first row was
impossible: `done_reason` never left the gateway, so the guard could not fire.

---

## Check 1 — diff matches the delta; strict-valid

`openspec validate gateway-token-accounting --strict` at `45412c2` →
"Change 'gateway-token-accounting' is valid", rc=0. **2 requirements / 8
scenarios**, matching the lead's count (counted from headings at the rev).

Each scenario has an executing test: `test_length_is_reported`,
`test_stop_is_reported`, `test_eval_count_is_the_upstream_value`,
`test_thinking_is_present_when_upstream_sent_it`,
`test_thinking_key_is_absent_when_upstream_sent_none`,
`test_every_prior_field_is_unchanged`, plus the agent-side
`test_length_stop_with_empty_content_raises` and
`test_empty_content_on_a_stop_stop_is_an_empty_answer`.

## Check 2 — additive only

Every pre-existing envelope key is present with unchanged meaning
(`test_every_prior_field_is_unchanged`), and the **request** the gateway sends
upstream is byte-shape-identical (`test_upstream_request_shape_is_untouched`) —
the change is response-side.

**hive-service is unaffected.** It calls `/v1/chat` (`llm_client.py:50`), not
`/api/chat`, so the shim rewrite cannot reach it. It does hit `ChatResponse`,
which gained three optional fields — I checked the emitted dict directly:

```
keys: [..., 'done_reason', 'eval_count', 'thinking']   # null when absent
```

`llm_client.py` returns `r.json()` wholesale and its callers read with
`data.get(...)`, so added keys are inert. No key was removed or renamed, so no
existing reader can break.

One honest caveat: `/v1/chat`'s JSON now carries three keys it did not before
(null-valued). That is additive in shape but not invisible — a *strict* client
validating an exact key set would notice. hive-service is not one, and the
fields are `Optional` precisely so old `/v1/chat` callers keep working. Noting it
so "additive" is not read as "wire-identical".

## Check 3 — thinking cannot reach training data

This is the check with real consequences, and the answer is structural rather
than a matter of anyone remembering:

- `answer_text` (`config.py:161-166`) reads **only** `message.content` and
  `done_reason`. It never reads `thinking`.
- Every `response_raw` in the agent is the return of
  `answer_text(resp.json())` — i.e. `content` — at `l3_planner.py:496/504/523/531`,
  `brain.py:33/69`. `trajectory_log.log_call` takes `response_raw` as a str and
  logs that field; it never stores the envelope.
- `build_dpo_dataset.py:89-93` trains `chosen`/`rejected` from `response_raw`.
- No path logs or persists the gateway body itself.
- hive-service never references `thinking` (grep over `app/`), and reads only
  `resp["content"]`.

So `thinking` reaches the wire and stops there. It cannot become `content`,
therefore cannot become `response_raw`, therefore cannot enter DPO pairs.

## Check 4 — tests run, mutant reproduced

Clean `git archive b843ddd`, private venv (four pure-Python deps):

```
python3 -m unittest tests.test_shim_passthrough    Ran 9 tests ... OK    rc=0
python3 -m unittest test_llm_think                 Ran 12 tests ... OK   rc=0
```

Mutant I applied myself — drop `done_reason`, hardcode `eval_count: 0` (the
original bug): **3 failures**, restored green. Matches the builder's "3 red"
claim for that mutant; I verified it rather than accepting it.

## Check 5 — no prod workload calls the test gateway

Answered without reading any secret or env value:

- `llm-gateway` is deployed **only** in `minecraft-test` (`1/1`, 183d). There is
  no `llm-gateway` Service in namespace `minecraft`.
- Prod (`minecraft`) runs three deployments — `aibot-agent`, `bot-registry`,
  `minecraft-server` — and **no** ConfigMap in that namespace references the
  gateway host.
- hive-service reaches the gateway via `LLM_GATEWAY_URL`, defaulting to the
  `minecraft-test` ClusterIP; that is a hive-service deployment, and prod's own
  workloads do not include the gateway as a dependency.
- Gateway access-log source IPs over a 50k-line window: 19761 hits from
  `10.244.3.1` (the kubelet health probe), and a long tail from **24 distinct**
  `10.244.2.x/.3.x` addresses. **No prod pod IP appears** (prod pods are
  `10.244.1.95/.110/.118`, `10.244.2.61/.226`, `10.244.3.205`).

**Scoped honestly:** I resolved *all 24* non-probe client IPs against every live
pod cluster-wide, and **not one belongs to a pod that currently exists**. So the
IP comparison proves no *currently running* prod pod called the gateway, and
cannot attribute the historical callers to a namespace — `10.244.2.0/24` is a
flat pod CIDR shared across namespaces, so an IP alone never identifies one. The
namespace evidence above (no Service, no ConfigMap, no deploy reference) is what
actually carries this conclusion; the IP comparison is corroborating only.

---

## N-1 (non-blocking): `/v1/chat` callers now see `thinking` too

`/v1/chat` is `response_model=ChatResponse`, so it returns the same three new
fields. hive-service ignores them, but if a future `/v1/chat` consumer persists
the whole response object rather than `content`, `thinking` would enter whatever
store that is. Not a defect in this change — the fields are additive and
documented — but worth one line in the spec so the next `/v1/chat` client author
knows the reasoning text is on that path. Cheap to add, not worth blocking.

---

## Notes on method

- The agent worktree is at `13076ca`, which **predates** `45412c2`; an early
  grep for `done_reason` in `agent/` returned 0 with a positive control also 0,
  which is what revealed the stale tree rather than a missing field. All agent
  evidence above is from `git archive 45412c2`.
- `kubectl` is not on this seat's PATH; cluster queries went via
  `ssh controlplane`. `kubectl: command not found` reported `RC=0` through a
  pipe — the empty result was the broken instrument, not an absence of pods.
