# Review 5a325cc — guards check the delete SEQUENCE, not just its existence

**Verdict: PASS. G1 and G2 are closed, F7 and F8 are not regressed, and the
rewritten guard block is stronger than what I asked for in two places.**

## Reproduced, not taken on report

Cloned the branch and reran all four of the builder's mutants plus four of my
own, restoring the original between each so no green is leftover state.

Builder's set:

  G1 delete-1-of-3         rc=1  "these ConfigMaps are created but never
                                 deleted: evals-code, evals-scout-cases-rebuild"
  G2 delete-after-create   rc=1  "a `kubectl delete configmap` appears AFTER a
                                 create/apply."
  F7 client-side apply     rc=1  (not regressed by the rewrite)
  F8 delete-as-comment     rc=1  (not regressed)
  unmodified               rc=0

My variants, designed to escape the new rules:

  H1 create, delete, create    rc=1  (delete interleaved after a write)
  H3 create name typo'd        rc=1  (set-equality by resolved name)
  H4 create of an UNDELETED    rc=1  (name not in delete set, added after it)
     name after the delete
  H2 create of an ALREADY-     rc=0  -- correct, see note below

H2 is worth stating plainly because it looks like a hole and is not. I added a
create for `evals-code` after the delete; `evals-code` is in the delete set and
no delete follows a write, so both rules hold. My test case was badly designed,
not the guard. Recording it so the next reader does not re-derive it.

## Two places stronger than my ask

1. G1's message names WHICH maps are undeleded, not just that "a delete exists".
   I asked for set-equality; naming the gap is more useful than asserting one.
2. `name_defaults()` resolves `REBUILD_NAME`'s self-expansion twice, so
   `${NAME}-rebuild` resolves to `evals-scout-cases-rebuild` rather than staying
   literal. Verified directly:

       defaults: {'NAME': 'evals-scout-cases',
                  'REBUILD_NAME': 'evals-scout-cases-rebuild',
                  'CODE_NAME': 'evals-code'}
       ordered ops: delete x3, then create x3

   That is the value the entire two-ConfigMap split depends on, and a single-pass
   resolver would have silently compared `${NAME}-rebuild` against a literal.

## The refactor did not degrade the other check

`name_defaults()` is now shared between the sequence guards and the Job-vs-script
comparison, so the two cannot resolve names differently -- the same class of bug
one level down, caught before it existed. The Job check also gained an explicit
`return 2` when it parses no mounts, so a broken regex cannot read as a pass.

## Suites

113 eval tests, 0 failures (counted by the runner). `bash -n` clean. Shipped
commands verified: one delete of all three names, then three creates, in that
order.

## Limit (unchanged, correctly held separate)

This asserts the printed commands are internally consistent with the Job. It
cannot observe kubectl. That is distinct from F7, which was a local bug fixable
locally, and the builder now keeps the two apart without blurring them.

## Note on the fix's origin

The builder fixed G1/G2 because a sentence in my F9 message described their whole
approach to this file -- "the check verifies verbs are PRESENT rather than the
sequence CORRECT" -- rather than just the two instances I could construct. That
was the right reading: G1 and G2 were symptoms, and the rewrite closes the class.
