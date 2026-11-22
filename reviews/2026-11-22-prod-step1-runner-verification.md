# Prod rollout step 1 (prod runner up, unused) — PASS

Row: `qitem-20261122101636-079a4c0de95fcf80`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Applies: `agent-script-runner` main `4eb9e4f` (merge of `bdc3b96` PASS). Plan: `docs/ptc-prod-rollout-plan.md` step 1.
All checks read-only. No secret values read, printed or compared; fingerprints and lengths only.

## Verdict

PASS. The live runner matches `4eb9e4f`'s manifest exactly, the prod agent is untouched, and the
runner is genuinely unused — it refuses unauthenticated calls and nothing in prod carries a `SCRIPT_`
name. Two of the lead's own statements check out against the live object, including the `/health` 404.
One gap for step 2 below, not a step-1 defect.

## (1) Live runner object matches the rev's manifest

`git show 4eb9e4f:manifests/agent-script-runner.prod.yaml` (15352 bytes) copied to controlplane
(15352 written back — bytes intact), then `kubectl diff -n minecraft -f`:

| check | result |
|---|---|
| `kubectl diff` vs live | **rc=0**, no output |
| negative control: same file with `replicas: 1 → 3` | **rc=1**, shows `-replicas: 1 / +replicas: 3` |

The negative control is the point: a diff that cannot see drift and a clean tree look identical.
This one reddens on a one-line mutant, so the rc=0 means "matches", not "did not run".

Independently confirmed on the objects themselves, not only via diff:

- Deployment: image `…agent-script-runner@sha256:1da521c1…`, `imagePullPolicy: Always`,
  resources limits `2 CPU/12Gi` requests `500m/4Gi` — identical to test's live values.
- Service `agent-script-runner`, ClusterIP, ports 8080/8081.
- NetworkPolicy: podSelector `app=agent-script-runner`, **2** ingress rules, from
  `app=minecraft-server` (the prod label, not `minecraft-test-server`) and `app=agent-script-runner-probe`,
  both under `namespaceSelector kubernetes.io/metadata.name: minecraft`. **No cardgame rule**, as the
  manifest's header says it must not have. The prod-copy label difference the manifest warns a blind
  text swap would break is correct live.

## (2) Prod agent unchanged, no SCRIPT_ env

| claim | live |
|---|---|
| image still `b2b274bf…` | confirmed, identical to the plan's rollback target |
| restarts | **0**; started `2026-11-22T10:10:07Z` (before the runner went up at 10:16) |
| `SCRIPT_` in deploy podspec | **0** |
| `SCRIPT_` in the *running pod* spec | **0** |
| container env names | `OMP_NUM_THREADS, MKL_NUM_THREADS, OPENBLAS_NUM_THREADS` only |
| `envFrom` | one source: secret `agent-config`; its keys matching `SCRIPT|RUNNER|TOKEN`: **none** |
| secretKeyRefs in the Agent | none |
| any ConfigMap in ns `minecraft` with a `SCRIPT` key | none |

The deploy-only check would not have been enough: `envFrom` pulls the whole `agent-config` secret in,
so a `SCRIPT_BOTS` key added there would appear in the pod with no visible env entry. I checked the
running pod's rendered spec and the secret's key names. Both clean.

## Health probes, from inside the prod agent pod

`wget` and `curl` are absent from the agent image, so my first probe returned "not found" for all
three endpoints — that is a statement about the client, not about the runner. Re-ran with `python3`:

| path | result |
|---|---|
| `/healthz` | **200**, 11 bytes |
| `/readyz` | **200**, 14 bytes |
| `/health` | **404** |

The lead's note that the plan's `/health` is the wrong path is correct, and not merely a guess:
`/health` really does 404 while the two probe paths 200. The plan text should be corrected so step 4's
verify does not cite a path that fails.

## Runner is unused: the token gate actually rejects

The plan says NetworkPolicy is unenforced on this cluster (flannel), so the token is the real gate.
I tested the gate rather than assuming it. A bounded pod in ns `minecraft` calling
`http://agent-script-runner:8080/health`:

| request | status |
|---|---|
| no `Authorization` header | **401** |
| `Authorization: Bearer bogus` | **401** |

A rejecting probe proves the gate exists; a probe that cannot refuse proves nothing. Both refused.

## Token: prod-only, distinct from test

Read via `jq 'keys'` and fingerprint only — no value printed at any point.

| | keys | minecraft fp | length |
|---|---|---|---|
| ns `minecraft` | `minecraft` | `sha256:93e2aa78` | 96 |
| ns `minecraft-test` | `cardgame`, `minecraft` | `sha256:b2a01be6` | — |

Prod has no `cardgame` key, matching P5 ("a test leak must not open prod"). Fingerprints differ, so
the comparison can discriminate — and my independent recompute reproduces the lead's test figure
`b2a01be6` by the same method, which is what makes agreement meaningful rather than coincidental.

The generator `scripts/make-prod-runner-token.sh` fingerprints `$STORED`, read back from the cluster
after the write, not `$TOKEN`. That matters: hashing the intended value prints the same result whether
or not the write landed, so it could never detect a bad write. Read-back makes the printed fp evidence.
I reproduced `93e2aa78` from a fresh cluster read-back, so the fingerprint describes what is stored now.

Runner startup log: `runner listening: contract 8080, probes 8081, games=minecraft` — exactly one game.

## (3) What else step 1 needed — step 0 is satisfied

Step 0 (**Backup**) precedes step 1 and was not in the lead's report, so I checked it independently:

- Hourly cronjob `minecraft-backup` (`0 * * * *`) ran at 10:00Z, job `minecraft-backup-29922360`,
  condition `SuccessCriteriaMet`, log `Backup complete: /backups/world_2026-11-22_10-00-16.tar.gz`.
- That completed **before** the runner was applied at 10:16Z, so the archive predates the change.
- Read back through a bounded read-only-mount pod on `minecraft-backups-pvc`:
  file present, **9,978,124,706 bytes**, `tar tzf` streaming real entries (`data/`,
  `data/usernamecache.json`, …). The archive reads back, as step 0 requires.

Note the plan's step-0 text says "newest at review time was …_06-00-16"; the 10:00Z archive is now the
relevant one and is the one verified here.

## Findings

None blocking step 1. Three for the lead, one of which matters before step 2:

- **F-1 (before step 2, not a step-1 defect):** `4eb9e4f` is the tip of `main` with nothing after it,
  and it is reviewed. But the agent image for step 3 must be the build carrying P6, which is a
  *neoforge-ai-player* change, not a runner change — so nothing here constrains step 3. Flagging only
  so the runner main is not mistaken for the step-3 source.
- **F-2 (plan text):** the plan's step 1 says `/health`; live is `/healthz` (and `/readyz`). Confirmed
  404 on `/health`. Correct the plan so later verify steps and rollback checks cite real paths. Not a
  deployment defect — the manifest's own probes already use `/healthz` and `/readyz` correctly, which
  is why the pod went Ready.
- **F-3 (informational):** prod's runner has no `nodeSelector`, while test's does
  (`sigma-vm-worker1`). The prod manifest documents this as deliberate ("the prod copy … will
  therefore also not pin a node — flagging so that is a deliberate choice rather than an accident").
  The pod landed on `sigma-worker2` with the requested 2 CPU/12Gi. Consistent with the manifest; noted
  only because the node differs from test's and a future reader will ask.

## Limits of this review

- I did not place the runner token in any request, so "the real token works" is inferred from the
  Deployment's `secretKeyRef` to the secret whose fingerprint I verified, not from a successful
  authenticated call. What I proved is that *unauthenticated* calls are refused, which is the property
  step 1 needs (unused means unreachable-without-token).
- Nothing about step 2 was verified: the mod jar copy, the server restart and the version line are
  untouched by this review.
- The backup entry count did not finish streaming before I stopped the pod; I verified existence, exact
  byte size and that `tar tzf` emits real entries, which is what "confirm it reads back" asks. A full
  count is not evidence of anything further.
