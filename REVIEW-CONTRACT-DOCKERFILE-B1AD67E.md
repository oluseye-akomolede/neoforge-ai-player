# Review — b1ad67e (contract `task` shape + Dockerfile test removal)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-12
Verdict: **PASS with two corrections, one of which should land before the rebuild.**

The builder held the rebuild for this review on the grounds that a Dockerfile
change makes the next image one nobody reviewed. That was the right call, and
it is why §2 matters: it changes what ships.

`openspec validate coded-agents --strict` → `Change 'coded-agents' is valid`
at `b1ad67e` (rev printed in the same command).

---

## 1. CONTRACT — the HOLD is closed, and closed properly

The prior HOLD was that `contract-v1.md` described `task` as
`{"goal":…, "progress":0.5}` — `progress` a **number** — while the Minecraft
binding emits `progress` as an **object** with a `phase`. Under the documented
shape, `task.progress.phase` is `undefined`, the guard reads busy, and the
script holds forever, presenting as "the bot is busy" rather than "the contract
moved".

`b1ad67e` fixes this correctly and goes past what I asked for:

- `task` is now documented as opaque with a named binding section.
- The idle shape is recorded verbatim:
  `{"bot":"Scout","state":"Standing by","progress":{"phase":"idle"}}`.
- It states plainly that **`progress` is an OBJECT here, not a number**, and
  that the `{"goal":…, "progress":0.5}` form illustrates other bindings.
- It names `if (snapshot.task)` as the wrong test *with the consequence* —
  true on a standing-by bot, so the script holds forever.
- It corrects the `state` description, which previously claimed task progress
  rode there. Task progress rides on the envelope's `task`.

Verified against `scout.js` at this rev: the comment block at `:47`-`:62` and
the contract now say the same thing, including that a directive with no
`progress` block must read as busy. The contract's quote omits
`"self_preservation":"ok"`, which `scout.js:47` shows; that is an abbreviation
in prose, not a contradiction of the field.

---

## 2. FINDING (should land before the rebuild) — the `rm` removes 9 of 11

`agent/Dockerfile` gains, after `RUN rm -rf ./scripts`:

```dockerfile
RUN rm -f ./test_*.py
```

with the comment *"Tests are development artefacts and have no business in a
runtime image … Nothing imports test_*.py, so their absence is not observable
at run time."*

Measured on a clean `git archive b1ad67e` export, simulating the `rm` in the
`WORKDIR /opt/aibot-agent` context where `COPY . .` has already run:

| | before `rm` | after `rm` |
|---|---|---|
| `./test_*.py` | 9 | 0 |
| `./tests/*.py` | 2 | **2** |

The two survivors are `agent/tests/test_directive_names.py` and
`agent/tests/test_health_readiness.py`. `rm -f ./test_*.py` is not recursive and
does not touch the `tests/` subdirectory, so they still ship in an image whose
own comment says tests have no business there.

**Severity: low, and I am not calling it a functional defect.** Neither file is
imported by anything in the tree (checked), and each imports only stdlib plus
`script_client` / `api`, so their presence breaks nothing at run time. The
defect is that the comment states an outcome the command does not achieve —
the same shape as the run-2 evidence problem, one level down: a claim and an
artefact, nothing comparing them.

**Verified fix** (run on a clean export, not proposed from reading):

```
before: 11 test files
sh -c 'rm -rf ./tests && rm -f ./test_*.py'
after :  0 test files
```

`rm -rf ./tests` alone also suffices for the two, but the pair is what I ran and
what I am vouching for. `agent.py` still parses afterwards.

---

## 3. FINDING (documentation) — the contract cites evidence that is not in the tree

`contract-v1.md` now says: *"`evidence/m2-run2/` records both live shapes from
TEST."*

At `b1ad67e`, `evidence/m2-run2/` does not exist. What exists is
`evidence/m2-run2-backup/`, holding `cm-agent-scripts-before.yaml` and
`deploy-before.yaml` — deployment manifests, not directive responses.

I checked every branch, not just this rev, in case it were misplaced rather
than absent:

```
for b in $(git branch -a --format='%(refname)'); do
  git ls-tree -r --name-only "$b" | grep -q "^evidence/m2-run2/" && echo "FOUND in $b"
done
-> (no output)
```

It is absent everywhere. This is the second instance today of a plan or contract
citing a review/evidence artefact as its basis where the artefact is not in the
tree that document lives in (the first was `REVIEW-M2-STEP4G.md` cited as
provenance for a pinned rev; the cited file was a different round's review and
not in that rev).

**The substance is not in doubt.** The idle shape's distinguishing values are in
the tree at this rev — `scout.js:47` and `deploy/agent-scripts.yaml:81` both
carry `{"state":"Standing by",…,"progress":{"phase":"idle"}}`. But those are the
*consumer* and the *script*, not a capture of the mod's response. A contract
that says "evidence/… records this" should point at something a reader can open,
or should say "measured from TEST, shape reproduced in scout.js:47".

Note also that `"Standing by"` traces in-tree to `agent.py:510`
(`api.chat(self.name, "Stopping. Standing by.")`) and to the test fixture at
`test_scout_script.py:74`. That does not make the shape wrong — the builder
measured it live twice — but it does mean the tree contains no independent
provenance for it, and the contract is currently the only assertion.

---

## 4. What I did not verify

Every cluster fact. I cannot reach `/opt/aibot-agent` in a built image, the
live mod's `/bot/{bot}/directive` response, or TEST. Findings 1 and 3 are about
what is in the commit, which I can read and run. The claim that the two live
shapes were measured from TEST rests on the builder's account, and I have said
so rather than implying I reproduced it.

I did not build the image. The `rm` simulation is on `git archive` output in a
shell, which is faithful to the glob and the `WORKDIR` but is not a `docker
build`.

---

## Verdict

The contract fix is correct, closes the prior HOLD, and should be kept as
written apart from §3. §2 is a one-word correction to a command
the builder is about to run; because the commit exists to change the image,
it should land before the rebuild rather than after. §3 (evidence
citation) can follow.
