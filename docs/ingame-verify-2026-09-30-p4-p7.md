# In-game verification — v15 P4 + P7 fixes (2026-09-30)

Image under test: `harbor.arcadia-ecs.local/aiplayermod/agent:chatstopfix-4215fd3`
digest `sha256:c5811a1ffe050cc81cc01bba276c0a4d4feeca759a65474399bdf29b5e22d414`
built from branch `minecraft-wt-deepseek` @ `4215fd3` (fixes `b64f8c1` P7, `4215fd3` P4).

Environment: namespace `minecraft-test`, deployment `aibot-agent-test`
(rolled from `chatstop-df0bb8c` → `chatstopfix-4215fd3`), 5 bots against the
test Minecraft server. Chat driven through the real entry point `api.inject_chat`.

## P4 — greeting message dropped (fixed)

Injected the exact failing message:

    api.inject_chat('Mystic', 'Player', 'Hi Mystic! Who are you?')

Agent log:

    [Mystic/chat] L3 plan layer: conversation, replying in character

Server chat log:

    <Mystic> I am Mystic, a mage who specializes in the arcane arts. I study
    enchantments, brew potent potions, and gather rare magical resources from
    the world around me.

Before the fix this message was silently discarded by the `skip_words` prefix
test (`"hi mystic!...".startswith("hi ")`), reaching neither converse nor plan —
matching the reported "nothing logged for Mystic". It now routes to converse and
Mystic replies in character. PASS.

## P7 — stop mid-exec-call did not stop the plan (fixed)

Injected a 2-subtask task, then injected `stop` while the log showed
`L3 EXEC call — subtask 1/2` (the window the bug lives in):

    [aibot.l3-planner] [Mystic] L3 EXEC call — subtask 1/2
    [Mystic/cancel] aborting orchestrator (nav shortcut: stop)
    [Mystic/nav] Direct stop (shortcut)
    [aibot.orchestrator] [Mystic] subtask 1 cancelled after exec call, before dispatch
    [aibot.orchestrator] [Mystic] plan finalized: cancelled

Agent log for the window contains **no** `Directive sent` line (pre-fix this
showed `Directive sent: CHANNEL {...} -> accepted (id=119)` after the cancel).
Mod log confirms every post-stop `cancelDirective` reports `active=none` and
`DELETE /directive (id=-1)` — nothing was ever accepted. Plan finalizes
`cancelled`, not `complete`. PASS.

## Rollback

    kubectl -n minecraft-test set image deploy/aibot-agent-test \
      agent=harbor.arcadia-ecs.local/aiplayermod/agent:chatstop-df0bb8c

The test deployment was left on `chatstopfix-4215fd3` for the reviewer/lead to
re-check. Prod was not touched.
