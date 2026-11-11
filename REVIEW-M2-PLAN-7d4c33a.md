# Review — M2 plan `7d4c33a` (lead conditions 1–2)

**Reviewer:** minecraft-reviewer@minecraft
**Rev under review:** `7d4c33a` — `plan: negative control cuts Scout off agent-side; script moves to a ConfigMap`
**Parent:** `be28201` (my previous review commit)
**Scope of diff:** `openspec/changes/coded-agents/M2-PLAN.md`, +124/−13, one file, plan only.
**Verdict:** **PASS**, with one required addition before step 2 and one cosmetic defect.

## 1. What the commit was asked to do

Lead conditions 1–2, 11:37Z:
1. The negative control must not stop the shared runner (cardgame depends on it).
2. The first script lives in a ConfigMap, not baked into the agent image.

Both are addressed, and the reasoning in each is better than the condition asked for.

## 2. Condition 1 — negative control, agent-side

The rewrite at §8 is correct on the point that matters: stopping the runner
"would break a peer's dependency to demonstrate our own resilience — the wrong
cost, paid by someone else." That is the right framing and I would keep the
sentence.

The two-mechanism split is also right, and for a reason the plan states
precisely: a closed port proves the *error* branch and returns immediately, so
it "would let a missing timeout pass the test"; the accept-and-never-reply
listener proves the *bounded-wait* branch (4.3). Requiring both is correct
because they fail differently.

**Required addition before step 2.** The plan says the cut is "agent-side, on
Scout alone" but never names the mechanism that makes it per-bot. It says only
that "Scout's script path in config becomes `/opt/aibot-agent/scripts/scout.js`".

Checked against the tree at `7d4c33a`:

- `agent/config.py` has **no per-bot env var** — `MOD_API_URL` (`:7`),
  `PROFILE_PATH` (`:87`) and the rest are process-wide. The Deployment is
  `replicas: 1`, so every bot runs in one process with one environment.
- Bot identity and per-bot behaviour come from a **profile dict**:
  `agent/profiles/scout.json`, consumed at `agent.py:155-157`
  (`self.profile = profile`, `self.name = profile["name"]`).
- **No profile carries a runner URL, endpoint or script field** — `grep -lE
  'url|runner|endpoint' agent/profiles/*.json` returns nothing, and `scout.json`
  has neither.

So the isolation is achievable and clean — it is one profile, not a shared
config — but the plan must say which file carries it. As written, a step-2
implementer reading "agent-side, on Scout alone" against a single-replica
Deployment with process-wide env has no stated route to per-bot isolation, and
the tempting shortcut (change the env var) would cut every bot off and breach
the lead condition. State it as: add `runner_url` and the script path to
`agent/profiles/scout.json`, read them in `scout.json`'s consumer alongside
`PROFILE_PATH`'s default, and leave every other profile untouched.

This is a plan gap, not a code defect, and it is cheap to close — which is why it
is a required addition rather than a hold.

## 3. Condition 2 — ConfigMap

Correct, and the §6 rewrite is thorough. The `readOnly: true` justification
("nothing in the agent should write its own instructions") is a good line.

**The most valuable passage in the diff is the `deploy/` warning.** It is not
decoration — I verified every claim in it against the tree at `7d4c33a`:

| Plan claim | Verified |
|---|---|
| `deploy/kustomization.yaml` sets `namespace: mindcraft` | yes, `:4` |
| manifest named `aibot-agent` | yes, `agent-deployment.yaml:4` |
| live object is `minecraft-test/aibot-agent-test` | builder's cluster read; I have no kubectl in this seat |
| mounts `agent-data` at `/opt/aibot-agent/data` | yes, `:35-36` |
| env from `secretRef: agent-config` | yes, `:25-26` |

So "treating `deploy/` as authoritative without that check would move the mount
into a namespace the agent does not run in" is a real hazard, correctly
identified. The step-2 run plan must discharge it as the §6 text requires —
either edit the live object's last-applied config or state which file owns it.

The rollback addition is also right and non-obvious: `rollout undo` reverts the
pod spec but **does not delete the ConfigMap**, leaving "a stale script a later
reader might mistake for live." Adding the delete, and the note that a
ConfigMap-only apply needs no `rollout undo`, covers both partial states.

## 4. Cosmetic defect — duplicated block

§6 (`:411-428`) now contains the convention block **twice**:

```
agent/scripts/scout.js          # the script source  (ConfigMap data key)
agent/scripts/scout.json        # {"revision": "sha256:…", ...}
```

followed immediately by the original, unannotated copy. The diff replaced the
prose and added the new block but did not remove the old one. Harmless to
meaning; it reads as unfinished, and the stale copy is the second thing a reader
hits. Delete the second fence.

## 5. Consistency of the change

- §6 decision 3 and §10 both carry forward pointers marking the old
  "stop the runner" rationale as superseded rather than deleting it. That is the
  right form and matches the convention established at `becd7d9`.
- §7's file list now names the ConfigMap and the live-object edit as separate
  rows, with the "see §6 on why not `deploy/`" pointer.
- No number in the plan changed in this commit; no digest is pinned (§6 keeps
  `sha256:…` as an ellipsis example).

## 6. What this PASS does not cover

Plan-only commit; no code moved and no probe was run. I did not re-read all 539
lines — §7's file list and §8's proof remain untested claims until step 2
executes. The cluster facts (`aibot-agent-test` 1/1, `mindcraft/aibot-agent`
scaled to 0/0) are the builder's reads; **there is no `kubectl` or kubeconfig in
this seat**, established earlier in this session, so I cannot confirm them and
have not.
