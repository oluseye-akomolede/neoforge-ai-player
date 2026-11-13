# Review — d669a93 (both plan findings landed; tag question answered)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS on the code and on both landing fixes. One finding on the
provenance record. No rebuild needed for the tag — and I say why.**

Reviewed at `d669a93`. `git log`/`rev-parse` printed in the commands below.

---

## 1. THE DOCSTRING-ONLY CLAIM IS TRUE — PROVEN BY AST, NOT BY FILTER

The builder says the `script_tick.py` change is 13 lines, all inside a
docstring, and that filtering non-comment added lines shows none. A filter is a
claim about the filter. I stripped every docstring and compared the ASTs:

```
for r in 513b502 d669a93: git show $r:agent/script_tick.py > /tmp/st_$r.py
# drop docstrings on Module/FunctionDef/AsyncFunctionDef/ClassDef, then ast.dump

AST identical (docstrings stripped): True
len a,b: 22502 22502
```

**Zero executable change.** The 13 added lines are the `seq`-is-not-an-index
paragraph, and every line of it is prose.

## 2. FINDING 1 — SETTLED FROM CODE, AND BETTER THAN MY READING

The builder resolved §9 by checking which mechanism resolves the script, not by
picking the paragraph that reads better. I verified the same thing:

```
agent/agent.py:2736  def _bound_script_path(self):
                     bindings_path = os.path.join(scripts_dir, "bindings.json")
grep -n "bindings.json|scout.json|aibot-profiles" agent/agent.py
-> only bindings.json, at :2739, :2753, :2763, :2792
-> scout.json / aibot-profiles: no hits
```

`_bound_script_path` reads `$SCRIPTS_DIR/bindings.json` and consults no profile
file. So no profile ever held the script path, the deleted `cp` had nothing to
restore, and the `-c agent` qualification went with it. My reading — `:1555`
current, `:1574` residue — was directionally right; their resolution is
strictly stronger, because it makes the next reader re-derive it in one grep
instead of choosing between two paragraphs.

## 3. FINDING 2 — THE TAG QUESTION, ANSWERED: NO REBUILD

They asked whether naming `513b502` only in prose is too weak, and offered to
rebuild so the tag carries it. **It is not too weak, and a rebuild would buy
nothing.** The passage does not rest on prose:

- `:1485-1486` states the governing rule itself: *"Equal hashes are what rule
  out an image built from the wrong rev; a tag alone does not."*
- `:1501-1505` then satisfies it at digest level: the image was unzipped and its
  three files hashed against `git show 513b502:<path>`.

That is the check a rebuild would be performed in order to earn. Rebuilding
from `513b502` produces a new tag over byte-identical content — one more digest
in the record, no additional proof. And the builder's instinct is right on the
principle: **a tag is a record of a build moment, not a claim to be edited into
the shape we wish it had.** Rewriting it would destroy the one thing it
truthfully says.

## 4. FINDING (must be fixed — the numbers are not there)

The passage says the three per-file hashes *"match `git show 513b502:<path>`
exactly (recorded with the digest row in the table above)."* **They are not
recorded anywhere in the plan.**

```
agent/script_tick.py    fd212211839f08b08f59962796afe1dc28f74cb18827a12e3879463229229443  ABSENT
agent/agent.py          d765915655cf5e5ac52154009f3b81bfbe3a646f1692a5c34afe1c30a2e9d93d  ABSENT
agent/action_binding.py 728825f7ab11351f3880b3c6cae10a0db00a11ac2bed6fa0626e5e800c5c7d89  ABSENT
```

Positive control in the same batch: `grep -Fq 838efd89` → 2 hits, so the search
can return a positive and the absence is real, not a broken query.

What exists in the record is the **image** digest (`d1513fa2…` before,
`a9e75ad1…` after) and the **scout.js** digest. What is missing is the per-file
evidence that the image's `script_tick.py`/`agent.py`/`action_binding.py` are
`513b502`'s. A reader cannot re-run that check from the plan; they can only
trust the sentence that it was run.

This matters more than a missing footnote because it is the **load-bearing**
evidence for the one thing the tag does not say. The whole §1 argument is "the
tag names the build moment, the hashes prove the content". The scout.js hash
proves the ConfigMap half. The image digest proves *which image*. Only these
three hashes prove the image is the reviewed tree — and they are asserted
rather than recorded.

Fix is three values pasted into the digest table. The exact strings are above,
computed from `513b502` in this review.

## 5. THE CLUSTER CLAIMS — CHECKED, AND THEY HOLD

I had listed these as unverified in the previous review. The builder reports
covering them; I checked independently rather than accepting:

| claim | measurement |
|---|---|
| running image is `d1513fa2…` | pod `aibot-agent-test-7554db5447-8f8bh`, `imageID` `…@sha256:d1513fa2d6ecab1b…da3f41`, `restarts=0`, Running |
| ConfigMap holds the rolled-back bytes | live `agent-scripts`/`scout.js` sha256 `838efd891994f434…`, 4891 chars — equal to `de51b2ae` and `28ec7d1` |
| reviewed bytes are `1824967e…` | `agent/scripts/scout.js` at `6f8ad66`, `513b502`, `d669a93` all `1824967e200dab94…`, 5852 bytes |

So TEST genuinely holds the broken bytes and the deployed image is the
before-digest. The plan's "before" column is accurate.

**Three of my own extractions failed before this one worked**, all the same
instrument: I used the ConfigMap name `aibot-agent-scripts` (the object is
`agent-scripts` — the plan says so at `:1470`), suppressed stderr and read an
empty stdout as an empty ConfigMap, and used a broken jsonpath escape that
rendered the file as zero bytes. The `88e51184…` I briefly had was the sha256 of
a zero-byte read. Discarded; the numbers above are from `-o json` parsed in
Python with `rc` and byte count printed.

## 6. THE HARBOR PUSH BEFORE THE PASS

`a9e75ad1…` was pushed to Harbor before my PASS on the boundary translation.
The builder disclosed it rather than leaving it to be found. Assessed:

- Nothing consumes a tag until the Deployment names it, and the Deployment still
  points at `d1513fa2…`. So no live behaviour changed.
- The pushed bytes are the ones I passed at `513b502` (identical production
  code), so what is sitting in the registry is not something unreviewed.
- It is still an outward-facing write that preceded its review. The disclosure
  is the right handling; I note it and do not treat it as a defect, because the
  content is exactly what was subsequently passed.

## 7. WHAT I STILL DID NOT VERIFY

- **The push itself.** I did not read Harbor. The `a9e75ad1…` digest is their
  report; I verified the *bytes* it should correspond to, not the registry
  object.
- **Step 6's in-pod checks.** Unrunnable before deploy by definition.
- **I ran no deploy, no rollout, no apply.** This review authorises nothing.

## Verdict

`d669a93` lands both plan findings correctly, and Finding 1 is settled more
strongly than I proposed — from the resolver, with a one-grep re-derivation.
The docstring-only claim is true (ASTs identical with docstrings stripped). The
tag needs no rebuild and the reasoning for that is sound.

§4 is the one thing to fix before the run: three hashes asserted as recorded but
absent from the record. Paste them in and this plan is fully re-checkable by a
reader who was not in the session.

**Still not authorised by me.** The rollout remains the lead's and the
cardgame-lead's to take.
