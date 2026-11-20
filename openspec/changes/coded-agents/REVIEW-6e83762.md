# Review: 6e83762 - F1 and F2 fixed, mutant-verified

**Verdict: PASS.** Both findings from my REVIEW-47c959a.md are closed, and I
confirmed each by applying the mutant to the real code rather than reading the
report. Suite from `git archive 6e83762`: `test_agent_script_branch` Ran 46
tests, OK, rc=0.

Parent is `47c959a`; no rebase drift. Reviewed from the archive, not a worktree.

**This PASS is for the two findings only.** The architecture defect the builder
found in the same rev - 47c959a's throwaway-botState claim - is NOT fixed and is
NOT mine to fix. It is correctly parked with the lead between options (a)/(b)/(c)
(see REVIEW-47c959a-WITHDRAWN.md, a61daa2). This commit's docstring now states
the real cost instead of hiding it, which is the right thing to do in a commit
that cannot fix it.

## F1 closed

`_dry_tick` now reads `if not handled and detail != "all actions refused"`, so a
post-run binding refusal is taken as "the script ran" rather than "the script
failed". Verified: `script_tick.py:390` is the only returned tuple carrying
`handled=False` with refusals, and its literal is exactly `"all actions
refused"`, so the compare matches the producer today.

M4 - restoring the old `if not handled:` - reddens
`test_a_say_only_script_still_binds`. Applied to the real `_dry_tick`, observed
1 failure, restored. The say/send/log family is genuinely protected now.

## F2 closed, and closed properly

The new test scans `vars(self.a)` for the memory marker instead of naming an
attribute, so it no longer depends on guessing a field name. I reproduced all
three adoption shapes the commit claims:

    adopt into _script_memory_live   -> 1 failure
    adopt into _script_memory        -> 1 failure   (the shape that used to pass)
    adopt into _last_dry_memory      -> 1 failure

The middle line is the one that matters: that is the exact mutant which stayed
green under the old test. It reddens now, so F2's inertness is genuinely fixed,
not papered over.

## N1 (non-blocking) - the memory scan is blind to a non-str adoption

The scan is `[k for k, v in vars(self.a).items() if isinstance(v, str) and
marker in v]`. An adoption that stored the blob as a dict, list or bytes leaves
it green - verified: `self._script_memory = {'blob': marker}` -> 0 failures.

Narrow in practice. `result.memory` is base64 `str` or `None`
(`script_tick.py:213-229`, `_encode_memory` accepts only str/bytes), so a str is
the realistic shape and the test covers the live hazard. Worth a note rather
than a fix: if the runner ever returns structured memory this scan goes quietly
blind again. A `repr(v)` substring check would cost nothing and cover it.

## N2 (non-blocking) - the refusal literal is a cross-module string compare

`agent.py:3056` compares against `"all actions refused"`, produced at
`script_tick.py:390`. No shared constant. A reworded detail string breaks the
carve-out silently - the gate would start rejecting say-only scripts again with
no error anywhere.

Mitigated today: `test_agent_script_branch.py:168` pins the mapping
`"all actions refused": (True, ...)`, so a rename reddens the suite. That is a
real guard and it is why this is a note. Still, the honest fix is a named
constant the producer and consumer both import, so the coupling is visible at
the definition rather than in two places that must agree.

## On the builder's own correction

The builder volunteered that the stub was the instrument twice, not the thing
measured, and rebuilt the test so it could not pass for that reason again.
That is the second time in two revisions they have caught their own blind spot
before I did (the first was the `import api` near-miss). Recording it because
the pattern matters more than either instance.
