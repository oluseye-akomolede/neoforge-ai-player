# Gate — M2 plan generation strategy and SKILL payload at 69a8fda

Rev: `69a8fda`, parent `aae3cb1`, `openspec/changes/coded-agents/M2-PLAN.md`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS on both follow-ups.** The generator is implementable as
described and I verified the parse target. One residual, non-blocking.

## Follow-up 1 resolved: the generator works, and I checked the source it parses

They chose (b), generate at build time from `DirectiveType.java`, with a
regenerate-and-compare test. That is the right choice for the reason they give:
the committed module makes the set reviewable in a diff, and the stale check
makes "do not type the literal" true in CI rather than in prose.

I verified the parse target rather than assuming it, because "parses the enum's
member list, not the file's prose" is a claim about a file I had not opened:

```
public enum DirectiveType {
    MINE, GATHER, GOTO, ... UNFUSE_BLOCK
}
```

37 bare uppercase names, comma-terminated, **no constructor arguments, no method
bodies, no trailing semicolon, no members after `}`**. `grep -cE '^\s*[A-Z_]+\s*\('`
returns 0. So a line-oriented parser reading `^\s*[A-Z_]+,?$` between the enum
brace and the closing brace is exact here — there is no ambiguity to resolve,
which is the one thing that could have made the generate step fragile. Good
choice of source.

**One guard worth adding, since the parser is the load-bearing piece:** the test
that regenerates must assert a *count* as well as byte equality. A parser that
silently matched fewer lines would produce a shorter module that still compared
equal to itself if the generator ran first in the same test. Regenerate-to-temp,
compare to committed, **and** assert the member count equals the count of lines
matching the member pattern in the Java file. Two independent readings of the
same source, compared to each other, is what makes drift loud.

## Follow-up 2 resolved: SKILL both ways

The both-ways test is the better of the two options I offered, for the reason they
give — a bare-target `SKILL` is a plausible author mistake and deserves a named
error rather than a silent no-op. And their citation is accurate:
`SkillValidator.java:59` does reject `SKILL` as a leaf ("a directive leaf must not
be SKILL — use a skill-ref node"), which is the real reason it is out of the
frozenset. That is a better explanation than the one I gave in my last review,
where I read the exclusion as incidental to `SkillValidator`'s handling rather
than as its explicit rule.

## Non-blocking: the set still cannot express payload validity

Admitting `SKILL` into `SCRIPT_DIRECTIVE_KINDS` and testing it both ways is the
right practical call, but it leaves `SCRIPT_DIRECTIVE_KINDS` as a set whose
membership does not mean "callable with a name alone" — `SKILL` is in it and is
not. That is fine as long as nothing later treats set membership as sufficient.
Worth one sentence in §2: membership means *the mod accepts this kind*, and
per-kind payload requirements are enforced at dispatch, not at membership. The
plan says this implicitly; stating it stops a future reader optimising on the
set.

## Note on scope

This is a plan review. I verified the plan's factual claims about the code it
cites (enum size and shape, frozenset size, the SkillValidator rule, the
`_VALID_DIRECTIVE_KINDS` purpose). I did not review any implementation of the
generator, because none exists yet in this range — the diff is the plan plus my
two prior review files.
