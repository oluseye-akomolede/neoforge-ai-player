# Review — contract clarifications delta at 57ca4d0

Rev under review: `57ca4d0` (branch `minecraft-wt-deepseek`; parent line
includes `55f29c5`)
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS on the contract delta (§4.1, §1). One sentence in the 2.1 task
text cites the wrong commit and contradicts the paragraph beneath it.**

Read from the rev via `git show 57ca4d0:…`. Ancestry confirmed: `55f29c5` is an
ancestor of `57ca4d0`; the rev is on `minecraft-wt-deepseek`. Scope: two files,
`contract-v1.md` (+30) and `tasks.md` (+24/−10), which is what was claimed.

## §4.1 — the shape inside `actions[]`

Correct, and correctly framed as a clarification rather than a change. The
paragraph says what it is not ("no field is added, removed or re-typed, the
envelope already carries `actions` as an array, and the freeze stands"), which is
what keeps this out of freeze territory.

The substance holds against the contract it sits in:

- `seq` is consistent. `:230-232` already return `{ok:true, seq}` from the three
  calls; the new table (`:253-255`) carries `seq` in the entry and the prose
  links the two — "the value returned to the script in `{ok:true, seq}`, so a
  script can correlate an entry with the acceptance it saw". That linkage is the
  part that makes the table usable rather than decorative: without it an
  implementer emits entries and has no way to match them to a script's view.
- "Rejected calls appear in no entry" is the right side of the boundary, and it
  matches §4.2, which defines what a rejected call returns.
- `api.remember`/`api.log` produce no entry "they ride the tick as result
  fields" — consistent with the spec's limits table (`:124`, `:126`, `:133`)
  treating them as fields rather than actions.
- `args`/`msg` carried "verbatim", not re-serialised, is consistent with §5's
  opacity rule for the envelope.

The reason given for adding it — "'opaque' tells an implementer nothing about
what to write" — is the same defect class as the condition-vocabulary gap at
`0c97a38`: a field required to hold something, with no statement of what. This
closes it at the right altitude, by binding the *minecraft* side rather than
forcing a shape on cardgame, whose `actions[]` stays theirs.

## §1 — Service ports and the cardgame Secret

Both correct.

- **Ports:** `:43` puts the DNS name on 8080, `:45` already stated the probe
  port as 8081, and the delta adds that the **Service publishes both**. That is
  a genuine gap closing, not a restatement: a probe port the Service does not
  expose is unreachable, so it is part of what the Service is. Cross-checked
  against `LAYOUT.md:147`, which already said "ClusterIP, ports 8080 (contract)
  and 8081" — so the contract is catching up to the deployment shape, not
  diverging from it. No Service/NetworkPolicy mismatch.
- **Secret:** name `agent-script-runner-token`, key `token`, namespace
  `cardgame`, created by minecraft as runner owner. Consistent with the
  "one token **per game**" rule directly above it and with §7.1's ownership
  line. **No secret value, prefix or length appears** — it is a locator, which
  is the correct way to write this into a spec.

## The 2.1 defect

They asked me to check exactly this, and it is not fully right.

The **new paragraph is correct and honest**:

> **The variant claim was FALSE until `9782ce4`**: `getQuickJS()` loads the
> **release-sync** build, not release-asyncify, so "we run the pinned variant"
> was untrue while the suite passed.

I verified the claim itself: `git log -S getQuickJS -- src/engine.js` shows it
introduced at `66b9549` and removed at `9782ce4`; `git log -S newVariant` shows
`newVariant` appearing only at `9782ce4`. So the paragraph is true.

**The sentence immediately above it is now wrong.** It reads:

> Our leg is built and tested against it (`agent-script-runner` 66b9549:
> `package.json` pins the exact version, the installed package resolves to it,
> and the suite asserts the pin rather than trusting it).

It cites **`66b9549`** as the evidence that the leg was built and tested
against the pinned **variant**. `66b9549` is the commit that used
`getQuickJS` — the sync loader. So the sentence points at the one commit whose
engine code demonstrates the exact defect the next sentence describes. The two
sentences sit adjacent and contradict each other.

The `package.json` half of that citation is true: the version pin is real at
`66b9549`, and the suite does assert the version. What was never true is "tested
against **release-asyncify**". Suggest narrowing it to what that commit actually
established — version pin and suite assertion of the version — and letting the
following paragraph carry the variant. Something like: "Our leg pins the exact
version (`66b9549`: `package.json`, resolved, asserted by the suite). The
*variant* claim needed `9782ce4` — see below."

**Not blocking the delta**, because the paragraph that follows states the truth
plainly and a reader who reads both sentences gets the correct picture. But the
first sentence is the one a reader skims to, and as written it is the defect
they asked me to look for having survived one sentence above its own correction.

## The tick

`[x]` 2.1 is claimed on two legs: ours and the shared one. The shared leg is met
(frozen pin `0281152` acknowledged, cardgame client committed against it). The
**ours** leg now depends on `9782ce4` — which is under separate review
(`REVIEW-9782ce4.md`) with an open finding on the fleet guard. The variant
loading in `9782ce4` is sound; the guard is what is open. So the tick is
defensible on the pin, but it is landing alongside a commit whose guard finding
is unresolved, and the task text should not be read as a clean bill for that
commit.

## Verified

- `openspec validate coded-agents --strict` and `show` at `57ca4d0`, in a tree
  with the change checked out: valid, 0 error/warning.
- Ancestry and branch as claimed; scope exactly two files.
- `seq` consistent between `:230-232` and `:253-255`.
- Ports consistent contract ↔ LAYOUT.
- No secret value anywhere in the delta.

## Not reviewed

- `9782ce4` — separate review, separate verdict.
- Step 3's emitter — not started.
