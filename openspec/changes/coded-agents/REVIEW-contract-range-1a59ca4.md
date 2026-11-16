# Review — contract-v1.md, 473db9f..1a59ca4

Range under review: `473db9f`, `8c68aae`, `1a59ca4` (contract-v1.md; `473db9f`
also touches tasks.md)
Mainline head at review time: `1a59ca4`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS**

Validated at `1a59ca4` in a tree that has it checked out (`git rev-parse` in the
same command): `Change 'coded-agents' is valid`, `show` 0 error/warning lines.

## A note on the range as given

The request named the range `57ca4d0..1a59ca4` (`473db9f`, `8c68aae`,
`1a59ca4`). But `57ca4d0..1a59ca4` is **two** commits — `473db9f` is the
*exclusive* lower bound and is not in it. Reviewing the range as written would
have silently omitted the 12Gi contract edit that the same sentence lists.

I reviewed `473db9f^..1a59ca4` instead, which is the three commits named. Worth
correcting in the row so a later reader does not take "reviewed 57ca4d0..1a59ca4"
as covering `473db9f`.

## The lead's four checks

### 1. No wire field added, removed or re-meant

**Holds, and structurally rather than by reading hunks.** I extracted the
field-ish lines (leading `-`/`|` bullet or table rows of the form
`` `name` ``-then-`:`) from the whole file at `473db9f^` and at `1a59ca4` and
diffed the name sets: **identical**. The count of code fences is unchanged, so
no block was opened or closed.

Every hunk in the range is prose: the 4Gi -> 12Gi rationale, the §7.1 owner
rule, and the §10 ports bullet. None declares, retypes or deletes a field.

### 2. `actions[]` shape from `57ca4d0` unchanged

**Holds.** Filtering the range's diff for `seq|actions|directive|args|call`
produces exactly one added line, and it is the word "caller" in the ports
prose. §4.1 at `1a59ca4` still reads `api.do` / `api.say` / `api.send` as
`{ok:true, seq}` and `api.remember` as `{ok:true}`, and the
"The shape inside `actions[]`" subsection still declares itself a clarification
with no field added, removed or re-typed.

### 3. The numbers match the runner's LAYOUT and measurements

**Holds, exactly.** Cross-read against LAYOUT at `5df8dcc`:

| quantity | contract `1a59ca4` | LAYOUT |
|---|---|---|
| instance limit / request | 12Gi / 4Gi | 12Gi / 4Gi (`:187-188`) |
| idle per bot | 46.7 MiB | 46.7 MiB (`:208`) |
| at the wasm cap | 113.9 MiB | 113.9 MiB (`:209`) |
| 72 at cap | 8.01 GiB | 8.01 GiB (`:209`) |
| guard budget | (not restated) | 11 GiB (`:219`) |

The `~2110 MB RSS` figure the contract now cites as the reason the old
arithmetic was wrong is the builder's measured number and is quoted in LAYOUT
as a measurement, not as a live limit.

### 4. `validate --strict` + `show` clean, rev printed first

Done as above. `validate --strict` is valid at `1a59ca4`; `show` prints no
error or warning line.

One caution for whoever runs this next: **`openspec validate` exits 0 while
printing `✗ [ERROR]`**, and `show` reports `0` error lines for a tree where the
change is not checked out at all (it says "No deltas found" under `validate`
instead). I hit both this session. Print `git rev-parse` in the same command and
read the sentence, not the exit code.

## On the lead's framing of the limit as a post-freeze change

The lead's call is that the instance memory limit is minecraft-owned and not a
wire change, so it may move after the freeze. The document supports that:
§7.1 now states **Owner: minecraft, as runner owner**, and §10's freeze
paragraph distinguishes frozen shape from per-game values the owning game may
raise. `max_sandboxes` is deliberately *not* in the freely-raisable set — a
quota rise is a request to the runner owner, granted only once the limit is
confirmed to cover it or raised first. That is coherent with the lead's call and
is what stops a quota rise from silently converting a cap into an OOM kill.

## Findings

**None blocking.**

Two notes, neither requiring a change to this range:

1. **`GIT_TAG` has no equivalent guard.** `5df8dcc` (runner repo, outside this
   range) makes an empty `GIT_COMMIT` fail the image build. `ARG GIT_TAG` still
   has no default and no check, so a tagged build with an empty tag labels the
   image `version=""` — a smaller hole than `revision`, but the same shape. Out
   of scope here; noting it because the reasoning that motivated the first guard
   applies to the second.

2. **The §10 ports bullet and LAYOUT now say the same thing, and must stay
   that way.** I raised the LAYOUT omission as a finding at `57ca4d0`; it was
   fixed at `eae7861`, and both documents now state the 8080/8081 rule with the
   same reasoning and an explicit "the two must not diverge" note. This is the
   third instance in this change of a correction landing in one document while
   its sibling still carried the defect — the contract is not the artefact that
   gets executed.

## Method

Claims verified against artefacts rather than prose:

- field surface diffed between the two revs rather than eyeballed;
- `actions[]`/`seq` checked by filtering the diff for those tokens;
- every number cross-read against LAYOUT's own lines, not against the
  handoff message (an earlier handoff in this chain had the request and limit
  inverted; the document was right and the message was wrong);
- validation run in the tree that has the rev, with the rev printed in the same
  command.
