# Review: 815b600 - done_reason scope set by census

Rev: 815b600 (neoforge-ai-player, branch ship-ca27-harness)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21

## Verdict: PASS. F-1 on a80429c is closed, and closed better than I proposed.

validate --strict rc=0. Census rc=0, functions=9 guarded=1 unguarded=8, run
from a clean `git archive` of the rev.

## The census is right, and it corrected me twice

Ran `agent/tools/census_structured_calls.py` from an extraction of 815b600:

  brain.py       think            :11    UNGUARDED
  l3_planner.py  call_plan        :473   GUARDED
  l3_planner.py  partition_fleet  :879   UNGUARDED
  l3_planner.py  classify_message :932   UNGUARDED
  l3_planner.py  call_exec        :1033  UNGUARDED
  l3_planner.py  call_replan      :1131  UNGUARDED
  l3_planner.py  refine_skill     :1244  UNGUARDED
  planner.py     decompose        :225   UNGUARDED
  planner.py     orchestrate      :377   UNGUARDED

All three sites I filed as omitted (brain.think, planner.decompose,
planner.orchestrate) are now in scope, so the requirement and its task list
cover the quantifier. The scope sentence at :107 now reads "every function in
the agent that sends format: \"json\" and parses the reply", which is the shape
I asked for.

Two of the builder's removals are corrections to MY census, and both are right:

- call_script (:1622) checks done_reason at :1684 before parsing, but it sends
  no `"format": "json"` and calls no json.loads - it pulls a JS code block out
  of prose. I listed it as GUARDED, i.e. as an instance of the rule, when it is
  not an instance at all. Its check is right for its own reasons.
- converse (:988) requests no JSON and parses none; `answer_text(resp.json())`
  parses the HTTP envelope, not a model reply. I listed it as one of the
  unguarded, when it should not have been counted.

So my "10 functions" was wrong in both directions: two spurious (converse,
call_script) and none missing. The verified set is 9, and it is now computed by
a tool rather than a hand list, which is the structural fix.

## The census gate is not inert

I appended a function to brain.py in the extraction:

  def probe_unguarded(model):
      r = client.chat(payload={"model": model, "format": "json"})
      return json.loads(r["text"])

Result: functions=10, rc=1, and stderr "DRIFT: expected 9 sources / 1 guarded".
Restored, rc=0, functions=9. The gate bites on a newly added call.

One limitation worth knowing rather than fixing: `requests_json_format` looks
for the literal `'"format"'` in the function's source segment. A call written
as a keyword argument - `client.chat(model=m, format="json")` - has no
`"format"` literal and is not detected. Every real call site in the tree uses
the dict form, and the detector's job is to catch additions in this codebase's
own style, so this is a note, not a finding. I mention it so that a future
refactor to kwargs does not silently empty the census: it would report fewer
functions, which trips EXPECTED_SOURCES, so drift still fires. The failure
direction is safe.

## Instrument failures of mine

1. I ran the census with a `--root` argument it does not accept, from the wrong
   directory. It printed "functions=0 guarded=0" and exited 0 - a zero I could
   have reported as a dead tool. The docstring says `python3 -B
   agent/tools/census_structured_calls.py`; I should have read the invocation
   before inventing flags.
2. I then piped it to `tail` and read "rc=0" on a run whose real exit code was
   1. That is the pipe-reports-last-command's-status trap, in my own memory
   notes, and I nearly filed the census as inert on the strength of it. Caught
   by re-running with output to a file and `echo $?` unpiped.
3. My first mutant used `format="json"` as a kwarg, which the detector does not
   match. It correctly did not change the count, and I briefly read that as the
   gate being blind to additions. The real dict-form probe above is the test;
   the kwarg run measured my probe, not their tool.
