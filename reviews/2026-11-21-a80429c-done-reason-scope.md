# Review: a80429c (done_reason for every structured call) + 2e7ea77 (lookup entry fields)

Revs: a80429c, 2e7ea77 (neoforge-ai-player, branch ship-ca27-harness)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21

## Verdict: PASS on 2e7ea77. PASS WITH FINDING on a80429c (F-1).

Both `openspec validate --strict` rc=0, run in the worktree that holds the
revs.

## 2e7ea77 - lookup entry fields: PASS, verified against the producer

The requirement's three shapes were checked field-for-field against
`test/fixtures/envelope-from-producer.json` in agent-script-runner:

  nearby.blocks[0] keys  {block, id, position}                     spec says {id, block, position}   MATCH
  nearby.mobs[0]   keys  {distance, name, position, type}          spec says {type, name, position, distance}  MATCH
  inventory[0]     keys  {count, display_name, durability, item,
                          max_durability, max_stack_size, slot}    spec says {slot, item, count, display_name, ...}  MATCH

The identity fields are exactly as the requirement states: a block uses `id`,
a mob uses `type`, an item uses `item`. The requirement's GIVEN/THEN read
correctly, and "returns the producer's stacks verbatim, MUST NOT normalise"
matches what look.inventory() does.

This came from my 8f9f9f6 note and the spec states it more precisely than I
did - it names all three shapes rather than the inventory one alone, which is
the better form.

## a80429c - done_reason: the named list is right, the scope undercounts

F-1: the rule says "**every** call that asks the model for a structured reply
and then parses it MUST check done_reason == length", but its own sizing
paragraph says "four other format:json calls", and the body enumerates six.
An AST census of all non-test agent code finds **ten** functions sending
`"format": "json"` and parsing the reply, of which **nine** do not check:

  call_plan        GUARDED (the model the rule cites)
  brain.think          unguarded
  partition_fleet      unguarded
  classify_message     unguarded
  call_exec            unguarded
  call_replan          unguarded
  refine_skill         unguarded
  output_evals/run.ask unguarded (eval harness, arguably out of scope)
  planner.decompose    unguarded
  planner.orchestrate  unguarded

The three omitted from the enumeration - brain.think, planner.decompose,
planner.orchestrate - are live, not dead code:

  agent.py:793   planner.orchestrate(...)
  agent.py:945   planner.decompose(...)
  agent.py:1850  planner.decompose(...)
  sessions.py:46 brain.think(...)

And they fail WORSE than a parse error, which is the failure the rule exists
to prevent. Each catches JSONDecodeError and substitutes a plausible result:

  brain.py:38-42       falls back to {"thoughts": "Failed to parse response", "actions": []}
  planner.py:271-274   returns PlannerResult([instruction])
  planner.py:435-438   returns [{"step": instruction, "assign": "any", ...}]

A truncated reply there becomes a silent wrong answer, not a syntax error and
not even an empty result. The rule's own argument - "that error names the wrong
cause" - understates these three: they name no cause at all.

The rule is stated generally and that generality is correct; what is wrong is
the count in its justification and the scope in tasks 4.x, which enumerates the
l3_planner calls plus classify_message. A reader implementing 4.1 from the task
list would leave three live sites unguarded while the requirement above them
says "every".

Fix: either widen the tasks to all ten (or nine, excluding the eval harness)
with a note on why planner.py/brain.py are in scope, or narrow the requirement
to name its scope as format:json call sites in the live request path. The
current text is a MUST whose enumeration does not cover its own quantifier.

## Verified elsewhere in a80429c

The classify_message self-correction is right, and right for the stated reason:
at :972 the only done_reason occurrence is inside the docstring at :943
("done_reason=length. Thinking was already off..."), a prose mention, not a
check. The AST census counts it as one hit and zero real checks. I made the
same error in my first pass - a 120-line window overran from partition_fleet
into classify_message's docstring and reported a check that was not there -
so the commit's account of how that miscount happens is reproduced.

call_plan at :501 does check, at :519, raising TruncatedAnswer before the
json.loads at :533. call_script does too. The two the rule says already
learned it, have.

## Instrument failures of mine

1. My first done_reason grep ran in MY worktree, which does not have a80429c,
   and returned zero for everything including `answer_text` - a function that
   exists. I nearly reported the rule as naming a nonexistent function. The
   rev was on ship-ca27-harness; `git merge-base --is-ancestor a80429c HEAD`
   said NO. Measured in the wrong tree, again: the same class of error as the
   phantom-rev sweep, caught the same way.
2. My per-function done_reason count used a fixed 120-line window, which
   overran partition_fleet's end (:908) into classify_message's docstring and
   reported a check in the wrong function. Redone with AST scoping by
   end_lineno.
