# Review 1adfc7f — recreate instead of client-side apply; guard both defects

**Verdict: the COMMANDS are right and F5 is properly closed. NOT PASS on the two
new guards: both can be satisfied by a comment, and one of them can never fire
at all.**

The builder's reframing is correct and is the most useful thing in the message:
my "delete the branch and the surviving path is the one we checked" comfort was
false, because the surviving path (the else branch) was also wrong. A check has
to encode the failure modes, not assume one path is honest. That is exactly the
lesson, and it is what these two guards tried to do.

The commands themselves are correct at 1adfc7f:

- delete-then-create, `--ignore-not-found`, three creates with explicit
  --from-file keys, split matching the size guard. Correct.
- client-side apply removed; the reason (262144 B last-applied cap) is right.
- the `items:` block in job-evals.yaml is intact and now commented as
  load-bearing. Good.

## F7 (NOT PASS) — the server-side guard cannot fire, ever

    if "apply -f -" in script and "--server-side" not in script:

Both operands scan the WHOLE FILE including comments. This script contains
`--server-side` in two places, both non-executable:

    :156  #     Too long". --server-side stores no such annotation.
    :167  echo "  # if you must re-apply ... use --server-side --force-conflicts"

So `"--server-side" not in script` is permanently False and the guard's
condition is unreachable. Demonstrated: I reintroduced the exact bug the guard
exists for (client-side `--dry-run=client | kubectl apply -f -` on the exec
ConfigMap) and check_apply_matches_job.py returned **rc=0**.

This is a gate that is inert by construction -- the shape my own notes call out
as "a passing gate can be inert". It passes today, and it would pass on the bug.

## F8 (NOT PASS) — the delete guard is comment-foolable

    if "kubectl create configmap" in script and "kubectl delete configmap" not in script:

This one does bite when the real line is removed (rc=1). But it survives only
because the phrase happens not to appear in prose. Replacing the command with
`echo "  # you should run kubectl delete configmap yourself first"` gives rc=0
with no executable delete anywhere.

## One root cause, one fix

Both guards should scan only the actionable lines -- the `echo "  ssh controlplane`
lines (strip full-line comments, then match), and for the server-side rule, test
the --server-side within the SAME command string rather than anywhere in the file.
That makes both guards able to fail, which is the only way they mean anything.

Both defects are the same class as the ones being fixed -- invisible on this VM,
fatal on controlplane -- reached one level up: the checker that was supposed to
make the invisible visible is itself blind to its own file's prose.

## F9 (minor, but it will be quoted) — the `items` comment states the wrong consequence

job-evals.yaml says dropping `items` makes "read_cases_dir start scoring plan
cases twice". It does not. read_cases_dir (extract.py:406) does
`by_kind[path.stem] = cases` -- stem-keyed OVERWRITE. Proved with a stale
plan.jsonl in exec/ plus 3 real ones in rebuild/: result is {'plan': 3}. The
later path wins and the earlier one is dropped SILENTLY.

So the real consequence is a silent partial loss whose outcome depends on
lexical path order, not a visible double-count. The conclusion (keep `items`) is
right; the stated mechanism is wrong, and the true one is worse. Worth a
one-line correction so nobody later reasons from the wrong mechanism.

## Suites (run here, counted by the runner)

113 evals tests across 6 modules, 0 failures. 43 agent tests across 3 modules, 0
failures. Matches the builder's figures.

## Still unproven (agreed)

Nothing parses what controlplane does with the printed commands. After F7/F8 are
fixed the guards will at least be able to fail on a local regression; the lead
remains the only instrument for the remote effect.
