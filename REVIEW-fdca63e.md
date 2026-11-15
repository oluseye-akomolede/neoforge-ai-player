# Review ca27b6e / fdca63e / ad2e077

**Verdict: ca27b6e PASS (ship it alone). fdca63e NOT PASS on (a): the
bot-state bullet licenses fabricating items. ad2e077 rides with it.**

Answers to the lead's three questions first, since those gate the after leg.

## (c) ca27b6e is replan-only — CONFIRMED BY HASH

Extracted each prompt from each rev and hashed the string body:

    rev        _PLAN_SYSTEM_PROMPT   _REPLAN_SYSTEM_PROMPT
    9e656b3    e781af2d8582 (5678B)  5e52d186e276 (513B)
    5ee0406    c8a006e8fe03 (6551B)  2065a2c01619 (739B)
    ca27b6e    e781af2d8582 (5678B)  2065a2c01619 (739B)
    fdca63e    f46065308767 (7331B)  2065a2c01619 (739B)
    ad2e077    f46065308767 (7331B)  2065a2c01619 (739B)

Plan at ca27b6e is byte-identical to 9e656b3; replan is byte-identical to
5ee0406. The claim is exact, not approximate. _REFINE_SKILL_PROMPT unchanged
across all five. **ca27b6e is genuinely shippable on its own.**

F2 is NOT reopened by removing the "If no prerequisite path can deliver the
stated goal, decline" clause. The surviving sentence at l3_planner.py:384-386
("planning around means adding the prerequisite steps that reach the exact goal
asked for") carries the same content, and the refuse definition still covers
"impossible here... something the server lacks". Removal is safe.

## (a) NOT PASS — the bullet licenses fabricating the items

l3_planner.py:369-371 at fdca63e:

    - "I am carrying zero items" is NOT a reason to refuse a task about storing
      or depositing. Plan: obtain the items, then store them. If the task does not
      say WHERE the items are, that is not missing information either — a bot
      finds its items in its own inventory, and if it has none it gathers them.

The lead is right and it is a real defect, not a tone problem:

1. "put my things in the chest" with nothing carried — "my things" are the
   PLAYER's items. The bot's inventory being empty does not mean the items exist
   somewhere the bot can gather; it means the bot does not have them.
2. "if it has none it gathers them" instructs the bot to acquire arbitrary
   items to satisfy a task about the player's items. That is manufacturing the
   goal's subject matter — a fabricated plan, which this same prompt calls worse
   than a refusal two paragraphs later ("A fabricated plan is worse than a
   refusal").
3. "that is not missing information either" closes off the one correct answer.
   For "put my things in the chest" with an empty inventory, the honest reply is
   `clarify`: whose things, and which chest. The prompt forbids asking.

Interaction with the lead's F2 ruling: "planned-around means adding prerequisite
steps that still deliver the exact goal". Fetching the player's items from a
known stash delivers the goal. Gathering random blocks to fill a chest does not
— it produces a full chest, which is a substituted outcome, forbidden by
spec.md:506. The bullet cannot tell the two apart, and its wording leans to the
wrong one.

### Proposed wording (replaces lines 369-371)

    - "I am carrying zero items" is NOT a reason to refuse a task about storing
      or depositing, when the items are ones the bot can obtain. Plan: obtain
      them, then store them. But "my things" in a task like "put my things in the
      chest" means the PLAYER's items, which may be nowhere the bot can reach:
      if the task does not say where they are and the bot is not carrying them,
      that IS missing information — `clarify` which items and where to find them.
      Never gather unrelated blocks to fill the container; a full chest that is
      not the player's goal is a substituted outcome, not a completed task.

## (b) The preservation tests are fragment-pinned and cannot fail on the rule

The tests pin literal phrases, not the semantics around them. Mutations applied
to fdca63e, suite run each time, original restored between each:

    M1 remove "never substitute a different, easier goal"   FAILED (1)  good
    M2 remove the whole "planning around means..." sentence  FAILED (1)  good
    M8 replace the bot-state bullet with fabrication perm    FAILED (2)  good
    M9 delete both refuse-example bullets                    FAILED (1)  good
    -- and, surviving:
    M3 delete the moon refusal text, keep the literal string    OK
    M4 invert moon to "plan: the moon is the end; fly there"    OK
    M5 delete the whole example block, keep "refuse" elsewhere  OK
    M6 replace "vague to act on" with "never ask anything"      OK
    M7 append fabrication to the gather sentence                OK

test_correct_refusal_examples_survive asserts `"fly to the moon" in text` and
`"dig to bedrock at the same time" in text`. M4 keeps both strings and turns the
moon into a PLANNED target — a direct inversion of the preserved-refusal
scenario — and all 15 tests stay green. The test measures substring presence, so
it cannot detect the rule being gutted.

test_missing_knowledge_is_not_missing_information asserts only the phrase
"that is not missing information either". M7 keeps that phrase and appends
fabrication permission to the next sentence. Green.

Direct confirmation, on the M7 tree:

    mutant sentence present: True
    'that is not missing information either' present: True
    'fly to the moon' present: True

This is the same failure mode as F7 on the eval harness: the check reads text
that includes the thing it is looking for regardless of meaning. For prompt
tests the fix is to assert the RELATIONSHIP, not the fragment -- e.g. that the
moon line contains both "fly to the moon" and "refuse", or that the bot-state
bullet does not contain "gathers them" unqualified.

## Other checks that passed

- Per-case verdict list includes unscorable rather than dropping them; the
  early-continue that silently dropped them was caught by mutation. Verified the
  list is ordered call_id/kind/shape/reason.
- ad2e077 rewords the delta from "transient" to the user-state category and adds
  the unknown-location scenario. `openspec validate --strict` valid.
- Suites: ca27b6e 113 evals + 8 prompt; ad2e077 117 + 15, all OK in clean
  archives.
- Stated limits are honest: the Job is unrun, and the plan rule is falsified by
  the lead's after leg, not by these tests.

## Instrument note (mine)

My first mutation attempt reported four survivors because I piped the runner
through `tail -2 | head -1` and the unittest summary goes to stderr into a blank
line. Re-ran capturing `^(OK|FAILED|Ran)`. M1/M2 had already reddened, which is
what told me the harness worked and only my filter was broken -- an implausible
uniform green again.
