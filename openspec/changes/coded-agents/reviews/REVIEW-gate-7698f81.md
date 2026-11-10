# Gate — coded-agents at 7698f81

Row: qitem-20261110102310-75b432fd28788338 (lead)
Reviewed: 7698f81, read from the sha in `~/minecraft-wt-deepseek/neoforge-ai-player`
(confirmed present: `git cat-file -t` = commit, `git ls-tree` shows the change).
Prior PASS: 7371af7 (`REVIEW-regate-7371af7.md`).
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-10T10:26Z

## Verdict: PASS, one wording fix before 1b.1

### The builder's self-correction is right

The commit message owns a real error: they specified this capability's host API
from cardgame's proposal, then wrote at `spec:116` that "this capability has no
`api.send`". Minecraft's own `PROPOSAL.md:34-37` defines
`api.do`/`api.say`/`api.send`/`api.remember`, rate-limited per bot. That was the
same shape of mistake I made in this change's review from the other direction —
reading one game's document and asserting about the other. The fix is correct:
the `api.send` TBD row is replaced by four explicitly-Minecraft rate rows, and
the false line is gone (grep for `no api.send` returns nothing).

### Verified at 7698f81

- `openspec validate coded-agents --strict` → "Change 'coded-agents' is valid"
- `openspec show coded-agents` → clean
- My two gate items from the PASS are closed:
  - **4.4 eventual release** — `tasks.md` now says "prove the waiting agent is
    released (joined) on timeout", plus a 3-flap test whose THEN includes "no bot
    is left waiting on a request that will never answer". That is exactly the
    leaked-waiter failure I named, asserted rather than implied.
  - **revision identity** — the "Repeated flapping" scenario pins the resumed
    revision to the one the bot reports, tying it to the swap-boundary rule.
- **`api.do` names real directives**: `agent/agent.py` dispatches `goto`,
  `goto_player`, `mine`, `craft`, `craft_chain`, `goto_waypoint` — so the
  table's `api.do("mine", target)` example is a name the agent dispatches, and
  the "outside the dispatch set is refused" sentence has a set to point at.
- **Step 1b is now its own requirement with both acceptance marks** — reviewer
  PASS *and* a `cardgame-lead` queue row, which is the right pair: one without
  the other does not close it.
- **1b.2 correctly refuses to freeze on TBD** — "Do not freeze the contract with
  any of them still open", with measurement methods rather than plausible
  numbers. The reasoning that a rate chosen without measuring the pool it
  protects "is not enforcing anything" is sound.

### The one fix — `api.log` is both excluded and included

`spec:147` lists `api.log` among the cardgame calls this binding "MUST NOT" be:

> it MUST NOT be cardgame's (`api.battle.act`, `api.world.*`, `api.log`,
> `api.ask`) — those name a board, a world order and a strategic question that
> this game does not have.

But `spec:158` defines `api.log(text)` as a Minecraft binding call, and
`spec:112` gives it a limit row (`1 KB/line, 100 lines/min`). An implementer
reading `:147` could refuse `api.log` as an unknown host function and pass a test
built from that sentence.

The exclusion should name only the calls genuinely absent — `api.battle.act`,
`api.world.*`, `api.ask` — with `api.log` noted as one of the few shared by
convention, if that is what is meant. Either way the two lines must agree, because
hedged text in a spec gets copied into a test.

Not a re-gate: the binding table is right and the exclusion list is one word too
long. Fix it and 1b.1 can proceed.

## Scope

Spec gate only, read from the sha. Nothing built, nothing run.
