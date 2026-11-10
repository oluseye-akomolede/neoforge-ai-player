# LAYOUT.md at c7878af — read against contract v1 (81a5905 + e2541fb)

Repo: `~/minecraft/agent-script-runner`, root commit `c7878af` (no parent, no
remotes, 12 tracked files, 0 `node_modules`).
Reviewer: minecraft-reviewer@minecraft
Verdict: **Two places where LAYOUT asserts against the contract.** Both are
fixable in LAYOUT under the lead's ruling (contract wins). Everything else in
the file is at or below the contract's strength, and two sections are stronger.

Read from `git show c7878af:LAYOUT.md` and `git show e2541fb:…/contract-v1.md`,
both by rev. Not read for style.

## Divergence 1 — LAYOUT puts the runner in a namespace, and names its ingress peers, the way the contract does not

The contract's ingress statement (§10, `:425-427`) is:

> namespace `cardgame`, podSelector `app=match-server` (their only caller), plus
> the minecraft agent pod. Nothing else.

LAYOUT (`:139-141`) reads: ingress allowed **only** from `-n minecraft-test`
pods labelled `app=minecraft-test-server`, and from cardgame's
namespace/pods "once they name their selector."

Three deltas, in increasing order of consequence:

1. **"once they name their selector"** — the contract has already named it, and
   the freeze is what settled it. LAYOUT defers a decision the contract records
   as made. Low consequence but it is the wrong reading of the frozen text.
2. **`app=minecraft-test-server` in `minecraft-test`** — the contract says "the
   minecraft agent pod" and does not name a namespace or a label set. LAYOUT
   picks test; production `minecraft` is listed in its own fact table at `:110`
   and is not in the policy. That may well be right for v1 (nothing is deployed
   to `minecraft` yet), but the file states it as the policy rather than as a
   v1 scoping choice, and the contract's phrase is the broader one.
3. **The runner's own namespace.** LAYOUT puts it in a new namespace
   `agent-script-runner` (`:103`), "its own, not `minecraft-test`", and flags the
   name as proposed (`:245`). The contract never names the runner's namespace —
   it gives only the cluster DNS name
   `agent-script-runner.agent-script-runner.svc.cluster.local` (`:38-39`), which
   encodes namespace `agent-script-runner`. So LAYOUT and the contract agree on
   the name, but the contract's DNS string is the only place it appears and it
   is a *consequence* of a namespace choice, not a statement that the namespace
   is `agent-script-runner`. If the namespace name changes, that DNS line in the
   frozen contract is wrong. Worth raising to the lead before deploy, because it
   is a contract edit, not a LAYOUT edit — and under the ruling, a LAYOUT change
   that renamed the namespace would be LAYOUT asserting something the contract
   already fixes differently.

Not a divergence: ports 8080/8081 and ClusterIP-only are stated in the contract
(`:38-41`), and LAYOUT repeats them correctly, including "so it never needs a
NodePort."

## Divergence 2 — the 4Gi limit's ownership is stated in LAYOUT and unowned in the contract

LAYOUT `:158`: `limits: { cpu: "2", memory: "4Gi" }`.
Contract §7.1 `:349-353` and §10 `:433`: the instance memory limit **is 4Gi**,
and `:349` calls it "a **contract term**, not a deployment detail."

Those agree on the value. Where they part is what LAYOUT says next, `:174-179`:

> **This is a promise the quota makes that memory must keep:** if 4Gi is not
> available on a worker, the cardgame quota of 64 is not real, and the honest fix
> is to lower that number, not to leave the limit where the pod dies first.

That is the **correct** reasoning and it is stronger than the contract, not
weaker — the contract states the limit but does not say what to do when memory
and quota conflict. However, it points at a gap the builder named and the
contract does not close: the freeze paragraph (`:7-10`) says the per-game numbers
`max_sandboxes`, `deadline_ms`, `tick_cpu_ms` may be raised by the game that owns
them as a value change. **The instance memory limit is not in that list.** So
cardgame can raise 64 without any contract change, and 64 × 32 MB × (plus
minecraft's 8) is exactly what sizes the 4Gi — meaning a per-game value the
contract says is freely raisable is constrained by a contract term that is frozen
with no named owner.

That is not a LAYOUT defect. LAYOUT is right to say "lower the quota rather than
let the pod die." It is a hole in the frozen contract: either the memory limit is
owned by the runner (and raising a quota is contingent on it), or it belongs on
the raisable list. I am not asking for a contract change unasked; flagging it
because LAYOUT surfaced it and the freeze has just made it expensive. **This is
lead territory, not the builder's.**

## What is stronger than the contract, and should stay

- **NetworkPolicy is the first on this cluster and the file says so** (`:108`,
  `:139`). It then requires the deploy-time proof I was told to look for: send
  from a namespace the policy does not allow, watch it **fail**, and "a request
  that succeeds means the policy is being ignored... a policy that is silently
  ignored is worse than none." That is the lead's requirement met exactly, and
  the reasoning ("reads as a control on a diagram while the port is open") is the
  right reason. Keep.
- **`:174-179` allocatable is 47/123/121 GiB (checked 2026-11-10), with 85 and
  72 pods already on workers 1 and 2.** The builder is right that "4Gi must be
  schedulable" is a promise, not a measurement, and says so in the text rather
  than asserting it. It is honest in the correct direction: it says what must be
  checked, which is exactly what a note *should* do when the check has not run.
  Not a defect — a correctly-labelled open item. Their item 2 is answered by the
  file itself.
- **The two wrong values, kept with their reason** (`:165-168`): 2Gi and 12Gi,
  both sized against minecraft's 256 instead of cardgame's own number. That is
  the right history to keep — it records the class of error, not just the fix.

## The evidence commit is clean

- 12 files tracked, `git ls-tree -r` shows **0** `node_modules`; `.gitignore:1`
  covers `probe/node_modules`.
- `git remote -v` prints nothing — no remotes, so nothing was pushed.
- Root commit, so nothing is back-fitted: the LAYOUT.md in `c7878af` is the first
  version in history. The builder's claim that it was committed unedited is
  checkable and holds — there is no prior rev to have been edited from.
- `probe/` is included as the measurement evidence for the stack values. The
  probes are the ones whose limits I independently re-derived earlier in this
  chain; the shipped value 256 KB matches my own measurements, so the evidence
  folder backs a number I have verified by a separate route.

## The builder's correction on their own scan

Accepted, and they went further than my correction. They were right that my
point 2 undercuts their evidence more than I said: an escaping-unaware awk scan
that "explained away" the one anomalous row is not a scan that "found no wild
rows." Same instrument as mine, different knowledge of why it read oddly. The
distinction they drew — "the row rendering correctly felt like permission" — is
the useful one, and worth remembering: a reader-side check passing does not make
a byte-level check right.

## Verified

- `c7878af` is a root commit (no parent), 12 files, 0 `node_modules`, no remotes.
- Contract read at `e2541fb`; §10 ingress `:425-427`, DNS `:38-39`, auth
  `:44-47`, memory limit `:349-353`/`:433`, freeze paragraph `:7-10`.
- LAYOUT read at `c7878af` as committed, not from the working tree.
