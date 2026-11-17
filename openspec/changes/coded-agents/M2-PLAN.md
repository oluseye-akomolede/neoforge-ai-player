# M2 — first bot runs its ticks from a script on TEST

Status: **PLAN, for review.** No code past step 0. Covers tasks 3.1, 3.2, 3.3,
4.3, 4.4, 7.2 and the path to 8.2.

Scope: ONE bot (`Scout`), on the TEST server, whose per-tick behaviour comes from
a hand-written JS script executed by the live runner
(`agent-script-runner.minecraft-test`, game `minecraft`). The existing planner
stays in place as the fallback. LLM authoring of scripts (7.1) is **out** — see
§8.

---

## 0. The decision that shapes everything: who calls the runner

**The Python agent calls the runner, not the mod (Java).**

Evidence, from `docs/aiplayermod-system-architecture.md`:

- The observe/think/act loop lives in the Python agent. §4.1: *"The agent spawns
  each bot in its own thread via `BotRunner`. Each runner follows an
  observe/think/act cycle"* — `agent/agent.py:152` (`class BotRunner`), loop at
  `_loop()` `:2584`.
- The agent already speaks HTTP to the mod over the bot REST API (`agent/api.py`,
  `_post` `:33`). A runner call is one more HTTP call from a process that
  already makes them.
- The mod is the game server process, and contract §7 deliberately keeps work
  *out* of it: the runner exists so script execution does not happen in the game
  server process (task 4.1). Calling the runner from the mod would put the
  tick's design back inside the process we removed it from.

**Why not the mod:** it would need an HTTP client, a retry/timeout policy and a
block-on-tick decision inside the server thread — the exact coupling §7's design
avoids. The mod's job stays "hold bot state, dispatch actions"; the agent's job
stays "decide what the bot does".

Consequence: the agent builds the snapshot (3.1), calls `/v1/tick`, receives
`actions[]`, and turns each into the **same** call it would have made from the
planner — `api.set_directive(...)` / the chat path. The mod is unchanged except
where §3.3 below says otherwise.

---

## 1. Task 3.1 — read-only per-tick snapshot

Built in the agent, from data it already fetches.

**This diagram is a leftover and the code is right** (reviewer, 13:06Z,
correcting 13:03Z — including my own repetition of it). `contract-v1.md:193`
specifies `{tick, server_ms, state, events, task}`, and `build_envelope`
(`snapshot.py:80`) emits exactly that. The nested `{"bot": …}` sketch below was
written before the contract settled and was never updated; it is the *diagram*
that diverges, not the implementation.

Three shape facts, which together are why the built script is written the way it
is — the original of each is a script bug this plan has already had:

1. Bot facts (`health`, `food`, `position`, `inventory`, `nearby`) are under
   **`state`**, not at the top level. `scout.js` read `snapshot.health`, which is
   `undefined` at every level, so its low-health guard silently never fired.
2. The running directive is at **`task`** (top level), not `state.task`. The
   cache originally built the envelope without passing it, making it `None`
   every tick.
3. `inventory` and `nearby` are under `state`, not top level, despite the
   diagram below placing them there.

Step 4 does **not** depend on resolving the diagram/contract difference — the
script reads the real envelope. Recorded so the run is not mistaken for a check
of §3's shape, and so the diagram is not cited as the contract.

```json
{ "bot": {"name","health","food","position":{"x","y","z","dim"}},
  "inventory": [...],
  "nearby": {"blocks":[...], "mobs":[...]},
  "task": {"directive","progress",...} }
```
*(stale sketch — superseded by `contract-v1.md:193` and by the three facts above)*

Sources that already exist in `agent/api.py`: `status(bot)` `:98`,
`inventory(bot)` `:101`, `blocks(bot,radius)` `:107`, `entities(bot,radius)` `:104`,
`get_directive(bot)` `:43`.

Copy, never a reference: `json.dumps` at the call boundary is the read-only
guarantee — the script gets bytes, and mutating them cannot reach the bot. The
contract says the runner deep-freezes it as well; that is defence in depth, not
the only guard.

**Three different times, named once, because this change has confused them three
times.** Do not interchange these:

| name | value | what it is |
|---|---|---|
| **tick cadence** | **2 s** (`TICK_DELAY`, `agent/config.py:89`) | how often the planner runs. This is the budget the snapshot competes against. |
| **`deadline_ms`** | 250 ms | the *runner's* wall budget for one script evaluation, sent in the request body. Unrelated to the planner's cadence. |
| **snapshot bound** | 300 ms | client-side cap on the cache refresh (§4.4); raised from 100 ms after the §1 measurement. |

An earlier draft compared a 150 ms snapshot against "the tick budget (250 ms)".
That is two errors in one sentence: 250 ms is `deadline_ms`, not the tick
cadence, and the cadence is 2 s, not 250 ms.

**Discovery risk — measured on TEST, 2026-11-11. The answer is: four calls do not
fit, and the reason is not what the risk assumed.**

The plan said to measure before assuming, so I did — bounded `Job` in
`minecraft-test` against the live mod, api key from `mod-api-key`, 40+ samples per
endpoint. Two different shapes came back — `/directive` **bimodal**, `/bots`
**deterministic** — and the distinction is the finding:

| endpoint | min | median | shape |
|---|---|---|---|
| `/bot/Mystic/status` | 2.4 ms | 3.0 ms | ~~consistently fast~~ **superseded — bimodal** |
| `/bot/Mystic/directive` | 2.4 ms | 42.2 ms | **alternates 2.5 ms / 42 ms** |
| `/bots` | 41.9 ms | 42.2 ms | ~~deterministic ~42 ms~~ **superseded — bimodal** |

Raw sample for `/directive`, consecutive draws:
`29.2 44.3 2.4 42.6 3.8 42.2 2.5 42.4 3.0 42.2`. There is no middle: a call
costs ~3 ms or ~42 ms, never ~20.

> **SUPERSEDED — see the re-run below.** The table above is the original ad-hoc
> measurement. The committed probe (`agent-script-runner/scripts/
> probe-snapshot-latency.mjs`, `7ba5e47`) reproduces the *refresh* verdict but
> **not** this per-endpoint shape: on every re-run `/status` was bimodal too,
> and `/bots` was not deterministic. Read the re-run, not this table, for any
> claim about a single endpoint. The *decision* (bound 300 ms, cache per tick)
> is unaffected — the refresh figure holds.

**Cause: two different things, not one.** For `/directive`, a real server-thread
hop: it either catches the server thread ready (~3 ms) or waits out the current
tick. 65% of `directive` samples paid it (26 of 40 ≥ 15 ms). For `/bots`, a
deterministic ~42 ms that is **not** a hop and whose cause is not established.
~~`status` is a bare field read and never pays either.~~ **Both clauses are
superseded by the re-run below: `/bots` is bimodal on that run, and `status` is
not fast.**

**Re-run of the committed probe, 2026-11-11 (`7ba5e47`), and it corrects the two
rows above.** Bounded Job in `minecraft-test`, 40 samples per endpoint plus 40
four-call refreshes, one discarded warm-up per endpoint, full body read. Every
cell below is recomputed from the committed log's draws, not by eye. **That
claim was false when first written:** the `status` min/max were carried over
from the superseded run instead of re-read, so the row said 1.4/61.5 where its
own log says 2.0/53.9. The reviewer caught it by recomputing from the log. The
cells are now the log's values, and the check that produced them is
`evidence/probe-7ba5e47.log` — recompute any cell from that file before
trusting it:

The **median column below is present for completeness and must not be quoted
as an endpoint characteristic** — see the caveat after the table. Read the
modes and the `≥15 ms` count instead.

| endpoint | min | median *(do not quote)* | p95 | max | ≥15 ms |
|---|---|---|---|---|---|
| `status` | 2.0 | 24.2 | 43.5 | 53.9 | 20/40 |
| `directive` | 2.3 | 41.8 | 62.7 | 76.8 | 27/40 |
| `bots` | 2.0 | 23.3 | 43.2 | 43.3 | 20/40 |

Full series, all 40 draws per endpoint: `agent-script-runner/evidence/probe-7ba5e47.log`
(committed at `e5595e0`; not pasted here — a 120-number block in the plan is not
more checkable than the file, and the earlier attempt to quote a 20-draw prefix
under an "all 40" label is exactly what went wrong).

The shape is the same on every sample: a call costs ~2–6 ms or ~42–44 ms,
nothing between, so **all three endpoints are bimodal**. The original table's
"`status` consistently fast" and "`bots` deterministic" both fail, and with them
the two-cause explanation above (a hop for `/directive`, a separate
deterministic cost for `/bots`). One shared stall, paid on roughly half of all
calls regardless of endpoint, is the reading the data supports.

**Caveat, and it is why only the refresh figure is decision-grade:** the
*proportion* of slow draws varies run to run. `status` was 20/40 here and 18/40
on the previous run, and its own median moved across three runs. A bimodal
series has no stable median — do not quote a per-endpoint median as a
characteristic of that endpoint; quote the two modes and the `≥15 ms` count.

**What does not change:** the four-call refresh on this run is **median 99.4 ms,
p95 128.7 ms, max 139 ms** — over a 100 ms bound about half the time, so the
300 ms bound and the per-tick cache remain the right decision for the right
reason. The refresh is stable across runs (medians 93–99, maxes 134–139)
because it sums four calls and averages out the fast/slow mix. That stability is
the argument for bounding and caching the *refresh*, rather than chasing
per-endpoint costs.

**Consequence for the 100 ms bound.** The per-call costs accumulate because they
are paid per call, not once per refresh — measured 4-call refresh:
**median 100.9 ms, max 129.5 ms, against a 100 ms bound.** So the bound as
written is unachievable on this path roughly half the time, and a naive four-call
refresh would intermittently trip the timeout and silently fall back to the
planner. That is the false-pass failure this milestone must not ship.

(The measured 4-call figure stands. The *explanation* first written here — that
the four calls land in different tick windows — was disproved by the interleaving
test described at the end of this section, and is withdrawn.)

**Revised design, and it is the cheap one.** The plan originally floated a new
aggregated `GET /bot/{name}/snapshot` endpoint in the mod. The measurement says
do **not** add one: a single endpoint that still hops to the server thread once
pays the same ~42 ms and buys almost nothing, while adding surface to the mod.
For the non-hopping reads the round-trip count is also not the dominant cost,
so folding them into one endpoint would not reliably get under 100 ms.

Two changes to §4.4 instead, both agent-side:

1. **Raise the read bound above the observed worst case.** A 100 ms bound sits
   just under the worst observed 4-call cost. Set `SCRIPT_TIMEOUT` to **300 ms**
   (well above the 129.5 ms observed max, still far below the 2 s cadence) so a
   normal expensive refresh does not masquerade as a failure. The bound exists to
   stop a *stalled* runner, not to refuse a busy one.
2. **Cache per tick.** Fetch the four values once per bot per planner iteration,
   TTL = the 2 s cadence, in `api.py` (agent-only, per the reviewer's ruling), so
   the refresh cost is paid once rather than per script evaluation.

**This supersedes the "if one snapshot costs more than ~150 ms" branch**, which was
reasoning about the wrong quantity: it compared against a per-call cost and against
`deadline_ms`, when the measured constraint is the cost of a *complete* refresh
(the 4-call figure in §1), and those per-call costs are paid per call rather than once per
refresh, which is why caching is part of the answer. Raising the bound and caching is
smaller than a mod endpoint and addresses the measured cause.

*Reproduce:* bounded Job in `minecraft-test`, 40 samples per endpoint, timing
`fetch` around a full body read against `minecraft-test-server:3100` with
the key from `secret/mod-api-key`. **The probe is now committed**
(`agent-script-runner/scripts/probe-snapshot-latency.mjs`, `7ba5e47`), so the
table is re-derivable: run it as a Job in `minecraft-test` with `API_KEY` from
that Secret; it reads the key from the environment and never prints it, and it
prints the full draw series so any quoted figure can be recomputed from the log.
The original ad-hoc Job was deleted and its numbers could not be re-derived; the
re-runs below are from the committed script. (Reviewer caught the earlier claim
that it was committed; an uncommitted probe is the same defect as quoting a
number from a script that no longer exists. Lead condition 3 was to fix exactly
this.)

**Correction on the mechanism (reviewer, 10:39Z — accepted, with one amendment).**
The cause is **not** a server-thread hop for all endpoints. Verified in source:

| endpoint | path | measured |
|---|---|---|
| `/status` | `getCachedStatus()`, a bare field read | 4–6 ms, consistently |
| `/directive` GET | `server.execute(...)` + `boundedJoin` | ~42 ms — a real hop |
| `/bots` | loop of `getCachedStatus()` over a `ConcurrentHashMap` | ~42 ms, consistently |

`/bots` does not hop, so hop cannot be its cause. I first read its 42 ms as
tick-phase alternation; a controlled test disproved that. Interleaving
`/status` then `/bots` 14 times gave `/status` 3.7–6.1 ms on **every** sample
and `/bots` 41.9–44.3 ms on **every** sample — no alternation, no correlation
with arrival time. The `/bots` cost is deterministic and endpoint-specific.
Its cause is **not established**; the 38 ms gap over `/status` is unexplained
by any difference visible in `handleBots` (`HttpApiServer.java:292-300`), which
is the same auth check plus a loop of field reads.

The shared 4-thread pool (`:77`) is real and the contention risk the reviewer
names is real — `BoundedWait.await` blocks a pool thread — but it does not
explain the isolated result above, where no concurrent directive traffic existed.

*Amendment on the arithmetic:* the reviewer is right that 42 ms is **less than**
one 20 Hz tick (50 ms), so "one tick plus overhead" was wrong. A uniform wait
for the next tick averages 25 ms with a 50 ms maximum; ~42 ms is a high draw
within one tick, not a tick plus anything.

**What this does and does not change.** The decision stands: bound at 300 ms,
cache per tick, no aggregated endpoint — a single endpoint that still hops buys
nothing, and an endpoint that no longer hops is not on offer for M2. What
changes is the confidence: the fix addresses `/directive`'s known hop and
amortises `/bots`' unexplained cost, but the tick cache does **not** remove
`/bots`' 42 ms on a cache miss. If M2's script path calls `/bots` once per
refresh, the per-tick cache is what keeps that off the critical path.

---

## 2. Task 3.2 — action binding limited to the existing dispatch set

The script can request exactly three calls (contract §4.1): `api.do(directive,
args)`, `api.say(text)`, `api.send(otherBot,msg)`. The runner returns
`actions[]`; the agent maps each to the path the planner already uses:

| action | agent path |
|---|---|
| `do` | `_l3_orchestrator_dispatch` (`agent.py:901`) — the existing dispatch, which routes mod directives through `api.set_directive` (`agent/api.py:428`) and the agent-side vocabulary through `api.equip_all` / `api.drop` / `api.vault_*` |
| `say` | the existing chat-send path (`agent/api.py:217 chat`) |
| `send` | the existing inter-bot message path |

Note `api.say` is a **runner** action (`binding.js:253`), not a mod directive —
it produces a `chat` call, never a `DirectiveType`. That is why it cannot be the
subject of a *directive*-parity check (§3.3).

**The dispatch set is not extended.** The plan does not restate the list and does
not hard-code its size: it is read from the symbol at runtime, because the number
has drifted three times in review (I wrote 51; the reviewer wrote 36; the set
holds 35). A literal here would be one more number to get wrong.

**Two different sets, and an earlier draft of this plan conflated them.** This is
the structural reason the count kept moving:

| set | size | what it is |
|---|---|---|
| `DirectiveType` (`src/main/java/.../brain/DirectiveType.java`) | **37** | every directive kind the **mod accepts** |
| `_VALID_DIRECTIVE_KINDS` (`agent/l3_planner.py:204`) | **35** | the kinds a **declarative skill leaf may use** |

They are not the same set. `AREA_LOOT` and `SKILL` are in the enum and **absent
from the frozenset**; the frozenset's comment says the kinds it omits "would fail
SkillValidator", which is a narrower rule than "the mod would reject it". An
earlier draft of this plan said the frozenset *is* the enum. It is the skill-leaf
**subset** of it, and that equals-sign was wrong.

**Which set does `api.do` intend?** This was previously implicit and must not
stay that way, because the two answers have different consequences:

- **If scripts may use the full enum (37),** the rejection must be built against
  its own set — `_VALID_DIRECTIVE_KINDS` would falsely refuse `api.do("AREA_LOOT")`
  and `api.do("SKILL")`, and the only symptom would be a bot quietly not doing
  what its script says.
- **If scripts may use only skill-leaf kinds (35),** that is a real restriction on
  what a script can ask a bot to do, and it belongs in the contract, stated,
  not implied by reusing the planner's private constant.

**Decision: `api.do` accepts the full `DirectiveType` enum (37),** built as its
own set, `SCRIPT_DIRECTIVE_KINDS`. Rationale is efficiency, not taxonomy: the
narrow frozenset is what `SkillValidator` and `SkillNode` consult for skill
**synthesis**, and it must keep doing exactly that. The new rejection needs its
own set, so building it against the 37 costs nothing and disturbs nothing.

### How `SCRIPT_DIRECTIVE_KINDS` is obtained — generate it, do not type it

An earlier draft said "`script_client.py` builds `SCRIPT_DIRECTIVE_KINDS` from
`DirectiveType`", which is not implementable as written: **`DirectiveType` is a
Java enum and Python cannot read it.** There is no Python import, no generated
mirror and no JSON export — `grep DirectiveType` across `*.py` returns exactly one
hit, and it is a comment. The sentence forbade a literal and then required one.

Three ways to resolve it, and why one is chosen:

| option | verdict |
|---|---|
| (a) hand-maintained 37-name literal in Python | **rejected** — reintroduces the exact drift the two-sets table exists to stop, now with two copies to desynchronise |
| (b) generate at build time from `DirectiveType.java`, failing loudly on drift | **chosen** |
| (c) mod exposes its enum over HTTP | **rejected** — §1 argues against new mod endpoints in M2 |

**Implementation:** a small generator reads `DirectiveType.java` and emits
`SCRIPT_DIRECTIVE_KINDS` into a generated Python module that is committed.

The parser can be exact rather than heuristic, and that is what makes this safe:
`DirectiveType.java` is `public enum DirectiveType {`, then 37 bare uppercase,
comma-terminated names, then `}` — no constructor arguments, no method bodies, no
trailing semicolon, nothing after the closing brace. A line-oriented parser over
that range matches the whole enum.

**The test asserts two independent things**, because either alone can pass on a
broken parser:

1. **Byte comparison:** regenerate to a temp file and diff against the committed
   module.
2. **Independent count:** assert the module's member count equals the number of
   lines in the Java file matching the member pattern.

Check 1 alone is not enough: a parser that silently matched only, say, the first
30 names would emit a short module that still diffs clean against itself. Two
independent readings of the same source is what makes drift loud rather than
silent.

### SKILL is accepted by the set but not satisfiable as a bare directive

Admitting all 37 includes `SKILL`, whose validity depends on its **payload**, not
its name — `agent/agent.py:3849` dispatches it as `set_directive(b, "SKILL",
target=sid, extra=...)` with a skill id. And `SkillValidator.java:59` rejects
`SKILL` as a directive leaf outright ("a directive leaf must not be SKILL — use a
skill-ref node"), which is precisely why it is absent from the frozenset.

**Membership means "the mod accepts this kind", not "callable with a name alone".**
Per-kind payload requirements — the `target=sid` that `SKILL` needs, a `block` for
`MINE` — are enforced at dispatch, where the payload is visible, not at set
membership, where it is not. Stated explicitly so a future reader does not
optimise on the set by assuming membership implies callability.

A flat name set cannot express "valid only with a resolvable id". Therefore:

- `SCRIPT_DIRECTIVE_KINDS` admits `SKILL` (the mod accepts it), but
- **§2's refusal test does not use `SKILL` as a plain accept case.** It is tested
  both ways: with a resolvable id (accepted) and with a bare target (rejected,
  with a message naming the requirement), or `api.do` is scoped to non-`SKILL`
  kinds and the restriction is stated in the contract. The plan adopts the
  both-ways test, because a bare-target `SKILL` is a script author's plausible
  mistake and deserves a named error rather than a silent no-op.

Two properties of that set matter for the refusal, and both are corrections to
the first draft of this plan:

- **The kinds are UPPERCASE** (`MINE`, `GOTO`, `SEND_ITEM`). Two places already
  upper-case before comparing — `agent/agent.py:904` for L3 directives, and the
  mod itself at `HttpApiServer.java:1341` (`body.get("type").getAsString()
  .toUpperCase()` before `DirectiveType.valueOf`). **Correction (lead condition
  4): an earlier draft said a script naming `"mine"` "would reach the mod and
  fail there". It does not — the mod accepts it.** Literal lowercase therefore
  works end to end today. The agent normalises anyway, so the two sides agree
  explicitly instead of relying on the mod's hidden forgiveness, and so the log
  line shows the spelling the mod used.
- **What IS broken is an unknown name.** `DirectiveType.valueOf` throws
  `IllegalArgumentException` inside the request handler, so the agent sees an
  HTTP 500 carrying no directive name — the error is far from the cause. The
  agent refuses that locally, naming the directive and its set. Implemented and
  tested in `agent/script_client.py` + `agent/tests/test_directive_names.py`
  (11 tests, `104a756`).
- **`DIRECTIVE_KINDS` is the mod's 37-constant `DirectiveType`, not the 35-name
  skill-leaf set.** **Lead ruling (11:47Z): `api.do` accepts ONLY these 37. The
  agent-side verbs are refused with a named error; widening the set is a later
  change.** That vocabulary is a disjoint 13 names — `ANCHOR_ON`, `ASK_PLAYER`,
  `DESPAWN_DRONES`, `DISMISS_GOLEM`, `DROP`, `EQUIP`, `PROVISION_TERMINAL`,
  `SHARE_LOCATION`, `SPAWN_DRONES`, `SPAWN_GOLEM`, `TEXT`, `VAULT_STORE`,
  `VAULT_WITHDRAW` — handled in `agent.py` without ever being posted as a
  `DirectiveType` (verified: intersection with the 37 is empty), plus the
  aliases `EQUIP_ALL`, `WITHDRAW`, `STORE`. A script calling `api.do("DROP",…)`
  **will** get a named refusal rather than a silent no-op, **once wired at
  4.3/4.4**. It does not today: `set_directive` (`api.py:428`) builds
  `{"type": name}` with no guard, and `script_client` has no caller outside its
  own tests, so the refusal is implemented and tested but not yet on any live
  path. Recorded in the contract, which previously said "51 names" for a set
  never identified.
- **`script_client` is added at step 1 but WIRED at tasks 4.3/4.4.** Nothing in
  `agent.py` imports it yet, so it is library code plus tests, not a live path.
  Its commit message reads as active dispatch; this clause is the correction.
- **`api.set_directive` does NO validation** (`agent/api.py:428`). It builds
  `{"type": name}` and POSTs. So the rejection described below did not exist
  before this change — this plan introduces it, in `script_client.py`, on the
  agent side, at `104a756`.

The runner deliberately does not validate names (contract §4.1 — the set is the
game's). The agent therefore resolves the name at the moment it applies the
action: case is **normalised** (matching the mod), and an unknown name is
**rejected and logged**, never passed through.

**Proof required:** a test that submits a script calling `api.do("NOT_A_REAL_-
DIRECTIVE")`, and asserts (a) the runner returns it as an action (it does not
validate), and (b) the agent refuses to dispatch it and logs the refusal. That
pair is the whole point of 3.2: the boundary is enforced on the side that owns
the set.

---

## 3. Task 3.3 — parity proof for one action

Pick **one** directive with an unambiguous, observable effect.

> **RULED at review, 2026-11-11 12:14Z — option (a) as a TWO-LAYER comparison.**
> `SAY` is not a `DirectiveType`: the enum has `CHANNEL` and no `SAY`, and chat is
> a separate endpoint (`api.py:217`). So there is no directive to compare
> against, and the original subject was a phantom.
>
> The reviewer also killed the naive form of (a): **every planner-path
> `api.chat` is an aside around an action** — `agent.py:359` (memory ack),
> `:374` (work area), `:470` (on my way), `:479` (stopping), `:1214` (chat
> reply); `sessions.py:230,391` (session chatter). The planner never emits
> speech *as* its action output; its action output is a `DirectiveType`. So
> `api.chat` vs `api.chat` would be the same function called from two places —
> a tautology that proves the endpoint works, which was never in doubt.

**The subject is the binding, not the endpoint.** The proof must exercise the
layer each path actually goes through:

| path | reaches the effect via |
|---|---|
| planner | directive dispatch (`DirectiveType` handler) |
| script | runner → `agent/script_client.py` binding → dispatch |

Method — two runs of the same bot in the same place:

1. **Planner path:** the bot reaches the effect through the existing dispatch.
   Record the observable log line and the sequence of API calls.
2. **Script path:** the same effect arrives via the runner and the binding
   layer. Record the same two things.
3. Assert the **API call sequence is identical** and the log line is identical.

If both paths call the same helper directly, there is **no binding under test**
and the comparison is vacuous — that is the failure mode this section exists to
avoid.

**The subject is `STORE_ALL`, ruled 12:16Z.** Naming it here rather than leaving
"the smallest one that still crosses the binding" is the point: an unnamed
subject in step 3 becomes an unbuildable test in step 4, and §8.2 item 3 defers
to this section, so without a concrete action §8.2 has no observable at all.

- **Not `IDLE`.** `IdleBehavior.java` contains no log call, no chat, no send —
  nothing observable. Ruled out by reading the file, not by preference. A
  parity check needs an effect that leaves a trace on both paths.
- **Not `CHANNEL`.** It takes `target`/`count` (`l3_planner.py:142-146`), which
  adds a formatting confound on top of the binding.
- **Not `MINE`.** A movement action's parity is confounded by tick timing and
  world state.

**`STORE_ALL` accepts a location, but nothing in this codebase sends one — and
the parity test constructs one deliberately.** An earlier version of this
section claimed `STORE_ALL` "takes neither", which is false. A later version
said both forms were "real in the planner's own vocabulary", citing
`l3_planner.py:142` pairing `STORE_ALL` with `("x","y","z","radius")`. That is
also false, and in the same way: **the tuple is the parameter list for the whole
two-directive skill signature, not for each directive in it.** `_SEED_SKILLS`
values are `(kinds, param_names)` and `_build_skill_extra` (`:270-272`) harvests
those names across the sequence and folds them into a `SKILL` extra. `x`/`y`/`z`/
`radius` are `AREA_LOOT`'s; `crop`/`count` are `FARM`'s. Neither entry gives
`STORE_ALL` a parameter. The mod's own seed specs agree — `SkillRegistry.java:154`
puts the coordinates on `AREA_LOOT` as `extra`, and `STORE_ALL` beside it is bare.

What *is* true is one level down: `StoreAllBehavior.java:63` does
`if (directive.hasLocation()) targetedContainer = BlockPos.containing(getX(),
getY(), getZ())`, and `:161` branches on `isStorageBlock(...)`. The behaviour
accepts coordinates. Nothing we can point at emits them, and for the main
producer that is structural rather than incidental: `_STORE_ALL_PATTERNS`
(`agent.py:1622-1623`) is
`r"(?:store|dump|deposit|stash)\s+(?:all|everything|inventory)|STORE_ALL"` — an
alternation with **no capture groups** — so the handler at `:1888-1889` returns
`{"type": "STORE_ALL"}` and *cannot* carry coordinates whatever the input text
says. It could not become coords-bearing without editing the pattern. The author
prompt (`skill_author.py:281`) and the mod's seed specs
(`SkillRegistry.java:154`) are bare for the same practical effect.

That the planner *cannot* emit a coords-bearing `STORE_ALL` is **not
established** — a raw model output outside a seed match is untraced. But nothing
in this repo is known to produce one, so the test would be building it.

So the parity test **constructs** the argument form rather than sampling one
the planner naturally emits. The form it constructs is the **coordless** one,
because that is what every producer in this repo emits — and a constructed
fixture should construct the *plausible* call, not one nothing here makes. Both
paths are issued the same bare `STORE_ALL`. The assertion is that the POST
bodies are byte-identical. This is still a real cost — a constructed fixture
proves the two paths agree on the call you wrote, not on the spread of calls the
planner actually makes — and the plan states it rather than letting "pinned"
imply "representative". The difference from a coords-bearing pin is *how* that
cost is paid: a coordless pin at least holds constant a form the planner really
produces, so a mismatch means the two paths disagree. A coords-bearing pin would
compare the planner against a call it never makes, so a mismatch would be
uninformative about parity.

**The form is taken from code, not from observation — and the plan says so.**
The TEST planner logs do not carry it: the agent's directive record is the
trajectory JSONL, and the store holds exactly **one** `STORE_ALL` record —
`agent_trajectories/trajectory-2026-08-14.jsonl:2`,
`{"bot":"bot1","model":"qwen2.5:14b","parsed":[{"kind":"STORE_ALL"}]}`,
coordless, `plan_ref` `offloop-livefire-1`, dated 2026-08-14. Three reasons it
is not treated as evidence of current behaviour: it is one record, it is three
months stale, and its `model` is `qwen2.5:14b`, not the `qwen3-coder:30b` the
profiles now name — so it is not even the current planner. It is recorded as
**consistent with** the structural argument, never as the observation that
carries it. The pinning rests on the structural argument above
(`agent.py:1622` no capture groups; `SkillRegistry.java:154` bare beside
`AREA_LOOT`). That is read from source, and it is a scoped claim: producers
enumerated, a raw model emission outside a seed match untraced.

The live check does not disappear — it moves. **The 8.2 run records the real
mod-side POST** for whichever form the planner actually emits, so the observed
form is captured during step 4 and can be compared against this pin afterwards.
If the run shows the planner emitting coordinates, that is a finding about this
paragraph, not a reason to reshape the test on the fly.

The pinning is load-bearing precisely because the comparator at `:1356` fires
**before any behaviour runs**: a coords-bearing and a coordless `STORE_ALL`
produce an identical POST body while their effects diverge (`:171` moves the
bot to the coordinates; without them it walks its own candidate list). The
comparator is branch-free *by design*, which makes it neutral between paths but
blind to argument-form differences — so the argument form has to be pinned by
the test, not left to chance.

**Observation point: the directive POST response, not a behaviour log line.**
`HttpApiServer.java:1356` returns `status: accepted` plus `directive.toMap()` on
*both* paths, from the same handler. Anchoring the comparison there means the
check does not depend on whether a given behaviour happens to log — which is
precisely what made `IDLE` unusable.

**Silence case (reviewer condition, 12:22Z): the assertion is the absence of the
API call, not the absence of output.** Step 4 must show no directive POST left
the agent for the silence scenario. A quiet log is not the same claim and passes
for the wrong reason when a call went out and failed at the far end — the
failure mode the comparator was chosen to expose. Where the scenario also
expects no chat line, that is a second, weaker assertion; it does not stand in
for this one.

**Rejected options, and why:**

- **(b) two-path comparison over a narrower directive** — kept as the
  later-check slot alongside `MINE` and `CHANNEL`; `STORE_ALL` is the primary
  because its argument form is a single optional coordinate triple with no
  formatting to normalise, the pinned call is the coordless form (above) that
  the producers actually emit, and the test constructs that form explicitly
  rather than relying on it. An earlier version justified this with "carries no
  args to format" — the retracted claim, which survived here after being deleted
  from the prose it came from.
- **(c) drop bare parity, rely on §8.2** — does not remove the phantom subject,
  it *moves* it: §8.2's game-side evidence was originally "the `say` line in
  the server log", which has now been corrected in §8.2 as well.

**The counter-case parity alone cannot catch.** Parity only proves the two paths
agree *when both act*. It cannot see a bug where the script path acts in a
situation the planner would have stayed silent in — both sides of the comparison
are silent, the sequences match, and the proof passes while the bot says
something it never should have. So step 3 gains a fourth run:

4. **Silence case:** a situation where the planner produces **no** action
   (condition false, or rate-limited). The script path must also produce none.
   Recorded evidence is the absence of the chat line *and* the absence of the
   API call — asserting only the chat line would pass if the call went out and
   failed.

---

## 4. Tasks 4.3 / 4.4 — reachability, bounded wait, fallback

The agent calls `/v1/tick` with a **hard bound**: connect + read timeout of
**300 ms**, set by the §1 measurement, not assumed. This is not the runner's
`deadline_ms` (250 ms) and not the 2 s tick cadence — see the table in §1.

The bound's job is to stop a **stalled** runner, not to refuse a **busy** one.
The original 100 ms was picked before the measurement and sits *below* the
observed worst 4-call cost (129.5 ms), so on a normal slow tick it would time out
and fall back — a silent failure indistinguishable from the runner being down.
300 ms clears the observed maximum with headroom while staying far below the 2 s
cadence, so even a fully timed-out script call leaves the planner running.

Because the snapshot is cached per tick (§1), the bound is applied to the cache
refresh, not to every script evaluation — the common path pays no network at all.

**The bound must be passed explicitly, not inherited.** `agent/api.py:33`
defines `_post(path, data=None, timeout=5)` — a **5 s** default, sized for
planner calls that may do real work. Reusing `_post` without an explicit
`timeout` would let one slow runner stall a 2 s tick five times over, and it
would do so silently because 5 s is a legal value. The script path therefore
calls `_post(..., timeout=SCRIPT_TIMEOUT)` where `SCRIPT_TIMEOUT = 0.3`, and
§7 requires a test that pins it: a unit test asserting the script path passes
0.3, which fails if someone drops the argument and falls back to the default.

States and behaviour:

| runner state | detection | bot action |
|---|---|---|
| connect refused | immediate (§4.3) | fall back to planner this tick |
| accepted but silent | read timeout at 300 ms (§4.4) | fall back to planner, log |
| 5xx / malformed | response check | fall back to planner, log |
| 200 ok | normal | apply `actions[]` |

**4.4 is the case that matters** and the one an easy test misses: a closed port
fails fast and proves nothing. The test uses a **listener that accepts and never
replies** (a socket that `accept()`s and sleeps), asserting the agent gives up at
the bound, the bot's tick still completes inside its budget, and the waiting
thread is **released/joined** on timeout rather than left hanging.

Player-visible requirement (from 4.3): the fallback must be *reported*, not
inferred from a motionless bot. The agent surfaces it through the same status
channel the dashboard already reads — a per-bot field such as
`script_state: "fallback" | "script"` with the reason. **Not building dashboard
UI for it in M2**; it is a data field, which is the minimum that satisfies "a
player must not have to infer it".

---

## 5. Task 7.2 — planner stays the fallback

No new mechanism: §4's fallback path *is* the existing planner. 7.2 is satisfied
by proving the planner still runs the bot when no script is runnable (no script
stored, runner down, or script rejected). The condition is explicit and logged;
the bot never has no path.

Ordering inside a tick: try script → on any failure, planner → if both fail,
idle-with-reason. The planner is never removed, only pre-empted.

---

## 6. The first script: where it lives, and the 6.x read path

**Hand-written**, for `Scout`, stored in a **ConfigMap** and mounted into the
agent — not baked into the agent image (review decision 3, `:537`; lead
condition 2, 11:37Z). An earlier draft said "a file in the agent's config",
which read as shipped-with-the-image and contradicted that decision:

```
agent/scripts/scout.js          # the script source  (ConfigMap data key)
agent/scripts/scout.json        # {"revision": "sha256:…", "game": "minecraft", "bot": "Scout"}
```

`revision` is the content hash, computed at load, so the runner's cache key and
the stored file cannot drift. Changing the script changes the hash, which the
runner treats as a new revision (contract §2 `script_revision` is required).

**The ConfigMap, concretely.** The live agent Deployment is
**`aibot-agent-test` in `minecraft-test`**, which currently mounts one volume,
`agent-data` (PVC), at `/opt/aibot-agent/data`, and takes env from
`secretRef: agent-config`. The script is added as a **second, additive volume**
— it replaces nothing.

**Read this before editing `deploy/`.** `deploy/agent-deployment.yaml` is *not*
what produces the live object, and following it blindly mounts into the wrong
place: `deploy/kustomization.yaml` sets `namespace: mindcraft` and the manifest
is named `aibot-agent`, while the deployment serving TEST is
`minecraft-test/aibot-agent-test`, applied by `kubectl apply` rather than
kustomize. A separate `mindcraft/aibot-agent` exists and is scaled to zero
(0/0). The step-2 run plan must therefore either edit the live object's
last-applied config or state explicitly which file now owns it; treating
`deploy/` as authoritative without that check would move the mount into a
namespace the agent does not run in.

```yaml
# deploy/agent-scripts-configmap.yaml   (new object)
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-scripts
  namespace: minecraft-test
data:
  scout.js: |
    <the script source>
```

**No `scout.json` key** (reviewer, 12:53Z; verified against
`deploy/agent-scripts.yaml` at this rev — its only data key is `scout.js`). An
earlier draft of this section showed one. The script's revision is not a file
the ConfigMap carries: `_revision_of` (`script_tick.py:58`) hashes the JS the
agent holds and sends `script_revision = sha256(source)[:16]` on the wire. That
is the hash of the **mounted bytes**, measured on the live pod as `823920fd7277b98b`
at 3526 bytes — byte-equal to `agent/scripts/scout.js`, since the ConfigMap
round-trip restores the trailing newline (§8.3.5 row 1 has the measurement).
Whoever executes §8.3.5 row 2
must compare against **that computed value**, not read a revision from the
ConfigMap — there is nothing there to read.

```yaml
# minecraft-test/aibot-agent-test   (added to the existing pod spec)
volumes:
  - name: agent-scripts
    configMap:
      name: agent-scripts
# ...and on the existing `agent` container:
volumeMounts:
  - name: agent-scripts
    mountPath: /srv/aibot-scripts
    readOnly: true
```

Scout's script path in config becomes `/srv/aibot-scripts/scout.js`. Edits
are a `kubectl apply` of the ConfigMap plus a pod restart — **no image build for
script storage**, which is the whole reason decision 3 chose this over baking
them in. `readOnly: true` because nothing in the agent should write its own
instructions.

**"No image build" means script storage ONLY.** Step 4 itself *does* build one
agent image, from the reviewed head, because the deployed image predates the
code step 4 exercises (`d45751d`, 2026-11-04 — see §8.3 deployable). Reading this
sentence as "step 4 needs no build" is the misreading it used to invite; the
ConfigMap needs no build, the code it enables does.

The ConfigMap is **not** in the runner's namespace or Deployment: the script is
read by the agent, which sends it to the runner in the tick body. The runner
stays stateless with respect to script storage, and a script edit needs no
runner change at all.

**How 6.x will read them later, without building 6.x now:** the scripts are
already plain files with a stable name→path convention and a content hash. The
player-visible read-only view becomes "list `agent/scripts/*.js`, show the source
and the revision" — a read over the same files, needing no new storage. That is
the design property worth having: **the storage choice for M2 is also the read
path for 6.x**, so building 6.x later needs no migration. Not to be built here.

Script content for M2 (deliberately boring — its job is to prove the path, not
to be a good bot): read the snapshot, emit one observable action when a condition holds,
otherwise return without acting, so the fallback and the script path are both
observable.

---

## 7. Files touched

| file | change |
|---|---|
| `agent/script_client.py` | **new** — `/v1/tick` client, bounded wait, snapshot builder |
| `agent/agent.py` | `BotRunner._loop`: try script, apply `actions[]`, fall back |
| `agent/config.py` | runner URL, token env, script path |
| `deploy/agent-scripts-configmap.yaml` | **new** — holds `scout.js` / `.json` (§6) |
| `agent/scripts/scout.js`, `.json` | **new** — the source, mirrored into the ConfigMap |
| `minecraft-test/aibot-agent-test` | **edit** — second volume + readOnly mount at `/srv/aibot-scripts` (see §6 on why not `deploy/`) |
| `tests/test_script_client.py` | **new** — 4.3/4.4 including accept-and-never-reply |
| `tests/test_action_binding.py` | **new** — 3.2 refusal, 3.3 parity |

**Not touched:** the mod (Java). No new directive, no new mod endpoint unless §1's
latency measurement demands one. No spec delta needed: this implements existing
task text, it does not change contract v1.

---

## 8. Proof of 8.2 on TEST — what shows the bot acting from the script

Not "the bot moved". A motionless bot and a scripted bot look the same from
outside, which is the defect this milestone is most likely to ship.

Three pieces of evidence, all required:

1. **Runner-side:** the runner's log line for the tick carrying
   `bot_id: "Scout"` and the script's `revision` hash, with `actions` non-empty.
   This proves the script ran and asked for something.
2. **Agent-side:** the log line where the agent applied action `seq` from the
   script — the same `seq` the runner returned, which ties the request to the
   effect.
3. **Game-side:** the directive POST response for the subject §3 names —
   `STORE_ALL`, **in the coordless form §3 pins (constructed from code, not
   observed)** — i.e. `status: accepted` with `directive.toMap()` carrying type
   `STORE_ALL` and no `x`/`y`/`z`, byte-identical between the script path and the
   planner path for the same bare call.
   Deliberately *not* a behaviour log line: `HttpApiServer.java:1356` emits this
   from the same handler on both paths, so the evidence does not depend on
   whether the behaviour happens to log.
   **This run also records the planner's own real POST**, so the coordless
   assumption is checked live here rather than only argued from source. If the
   planner emits coordinates, record that — it is a finding against §3's pin.


   **The silence case asserts the absence of that POST specifically — that no
   directive request left the agent — not the absence of a log line or chat
   message.** A quiet log also passes when a call was sent and failed at the far
   end, which is the failure this comparator exists to make visible.

   The argument form is part of the evidence, not incidental: `:1356` fires
   before the behaviour runs, so a coordless and a coords-bearing `STORE_ALL`
   give the same POST body but different effects. Pinning the coordless form —
   acknowledging that the test constructs the call rather than sampling the
   planner's spread (§3) — is what keeps this comparator honest.

   **The test must take the directive from the script, not write it.** A bare
   `STORE_ALL` has no arguments to smuggle a value through, which removes the
   coordinates as a possible harness-written constant but does **not** remove
   the defect: a harness that synthesises `{"kind": "STORE_ALL"}` on both sides
   still compares two things it wrote. The `kind` itself must come from the
   script. The test reads the action out of the runner's returned `actions[]`
   and feeds *that* to both paths. If the harness writes both bodies itself, the
   assertion compares two things the harness wrote and proves nothing — the
   in-memory thread assertion's defect in a new coat. The assertion is allowed
   to fail only because the script chose the directive; that is the whole of
   its force.

   The exemption is **positional, not intrinsic** (reviewer, 12:20Z):
   `StoreAllBehavior.java:171` calls `player.moveTo(targetedContainer...)`, so
   the coordinates form *does* move the bot — the ground on which `MINE` and
   `PATROL` were excluded as subjects. It is a valid subject here only because
   §8.2 compares the response emitted at `:1356` before any behaviour runs. If
   this evidence is ever re-pointed at game-side motion, that objection applies
   and the subject must be revisited.

The three together rule out every false pass: runner-only fails to show the bot
acted; game-only fails to show the *script* caused it; agent-only fails to show
either end. **A negative control is part of the proof:** make the runner
unreachable **for Scout only**, confirm Scout falls back to the planner and logs
it with a reason, then restore it and confirm Scout returns to the script.
Without that control, "it works" is untested against the failure it is meant to
survive.

**The control must not stop the shared runner** (lead condition, 11:37Z). The
runner in `minecraft-test` is shared: cardgame calls it from their own test
account, so stopping it to prove our fallback would break a peer's dependency to
demonstrate our own resilience — the wrong cost, paid by someone else. The cut
is therefore **agent-side, on Scout alone**, and the runner keeps serving every
other caller throughout. An earlier draft of this section said "stop the
runner"; that is the version that would have done it.

**Which config, exactly — and the wrong answer is the obvious one.** The naive
reading of "agent-side" is a new environment variable (`RUNNER_URL`). That would
cut off **every** bot, breaching the very condition it appears to satisfy:
`agent/config.py` has no per-bot environment — `MOD_API_URL` (`:7`),
`PROFILE_PATH` (`:87`) and the rest are read once, process-wide — and the
Deployment runs `replicas: 1`, so all bots share one process and one
environment.

Per-bot state comes from the **profile dict** instead, and that is the only
per-bot unit that exists. The live loader is `load_profiles()`
(`agent.py:3186`), called at `:4244` inside `run()`, which reads **every** JSON
file in `agent/profiles/` and then does `for profile in profiles: runner =
BotRunner(profile)`. `BotRunner.__init__` (`agent.py:155`) takes that dict and
reads `name`/`model`/`specializations` from it.

Because the loader globs the directory, **adding keys to `scout.json` needs no
loader change at all** — the new fields arrive at `BotRunner` automatically.
The only code that must learn them is the consumer at `:155`. So the mechanism
is:

- `agent/profiles/scout.json` gains **`"script"`** (`/srv/aibot-scripts/scout.js`).
  The key is `script`, not `script_path`: the consumer is
  `agent.py:2639` — `path = (self.profile.get("script") or "").strip()` — and a
  plan naming a key the code does not read is the `load_profile` defect again,
  one profile field instead of a function. Confirmed against the code at
  `4035605`, not against the prose above it.
- The runner URL is **not** a profile key. It is `SCRIPT_RUNNER_URL`, an
  environment variable read once at `script_tick.py:43`. It is process-wide
  because a Deployment has one process for all bots, and it is empty by default
  so an unconfigured pod falls through to the planner.
- **No other profile is touched.** `agent/profiles/*.json` contains no
  `script` field today, so this adds one field to one file rather than altering
  a shared default.
- Absent field means fall through to the existing behaviour, so a profile
  without `script` behaves exactly as it does now.

The isolation is therefore **one file, not shared state** — which is what makes
it clean. It is also why the plan must name it: an implementer reading
"agent-side, on Scout alone" against a single-replica Deployment with
process-wide env will reach for the env var, and the result would be a proof that
passes while secretly cutting off every bot.

> **DELTA (lead ruling 10:50Z, row `…1b24fe6e9c67c4c9`) — the last clause above
> is too strong and is corrected here rather than left to contradict §8.4.4.**
> A process-wide `SCRIPT_RUNNER_URL` cut is *not* a proof that passes while
> cutting off every bot, provided only bound bots exist. `_get_script_tick`
> returns `None` for a bot with no bound script path **before any `ScriptTick`
> or transport is constructed** (`agent.py:2808-2817`), so an unbound bot never
> reads the variable. The danger is real only if another bot is bound — hence
> §8.4.4's requirement to prove Scout is the **only** key in the live map, and
> that the other four bots' tick lines are unchanged across the arm. With that
> proof the env cut is agent-side for Scout alone. This delta narrows the
> constraint; it does not delete it.

Two agent-side ways to make the runner unreachable for one bot, both purely
config:

- **Closed port.** Point Scout's runner URL at a port nothing listens on
  (e.g. `127.0.0.1:1`). Proves the connection-refused path, which is fast and
  unambiguous.
- **Accept and never reply.** Point it at a listener that accepts and never
  answers. Proves the *bounded wait* (4.3), which the closed port does not
  exercise at all — a refused connection returns immediately and would let a
  missing timeout pass the test.

Do **both**, because they fail differently: the closed port tests the error
branch, the silent listener tests the timeout branch. The same
`tests/test_script_client.py` case covers the second (4.4's
accept-and-never-reply); the proof on TEST uses whichever the run plan can
configure without touching the shared Deployment.

> **DELTA (lead ruling 10:50Z).** "Without touching the shared Deployment" is
> narrowed: the *runner* Deployment must not be touched — it is shared with
> cardgame. The **agent** Deployment may be patched for an arm, because it is
> ours and the cut reaches only bound bots (§8.4.4, with its proof
> requirements). What remains forbidden is cutting the runner service itself,
> and cutting in a way that silently takes other bots with it.

Evidence is the same shape as the positive case, and must show all three
transitions in the agent log: **script → fallback (with reason) → script**. A
control that shows only "it fell back" does not show it recovered.

---

## 8.3 The TEST run plan (step 4, Part B)

**Status: proposed, not executed.** Nothing below has run. Every cluster fact in
it was read at 12:4xZ from `minecraft-test` and is true of that moment only.

### 8.3.0 MUST NOT TOUCH — read before the first command

This is a TEST-only change. Two nearby namespaces are traps:

| Namespace | What it is | Allowed here? |
|---|---|---|
| `minecraft-test` | the only namespace this plan touches | **yes** |
| `minecraft` | **PROD** — `minecraft/aibot-agent` is the live player fleet | **no, never** |
| `mindcraft` | stale — not a live environment, do not use as a control | **no** |

Rules that follow, and every command in this plan obeys them:

1. **Every `kubectl` line names `-n minecraft-test` explicitly.** No command
   here relies on a current context, a default namespace, or a `-A` form that
   could match a prod object by name. `kubectl get deploy aibot-agent` without
   `-n` is the exact command that would resolve to PROD.
2. **Never `-A` / `--all-namespaces` for a write.** Reads may fan out; writes
   may not. A `delete` or `apply` scoped to all namespaces would reach prod.
3. **Prod is read-only in this plan, and ideally not read at all.** The rotation
   earlier today already confirmed prod carries a different key; nothing in step
   4 needs prod, so nothing in step 4 reads it.
4. **The runner is shared.** The control run cuts Scout off agent-side only and
   never stops `agent-script-runner` — other work uses it (lead, 11:37Z).

A command that does not visibly say `-n minecraft-test` is a defect in this plan,
not a shorthand. Add the flag or do not run it.

### 8.3.1 What is true of the cluster before this plan

| Fact | Value | How read |
|---|---|---|
| Image (currently deployed) | `agent@sha256:9de2a68c370f5eafffae77aa8a89e9fdca43dcb840cde35e1bb659b19a142baf` | `kubectl -n minecraft-test get deploy -o jsonpath` |
|       — built from | **`d45751d`** (2026-11-04 04:39Z) | the pod's `/opt/aibot-agent/agent.py` sha256 `2fc54346…7164a` matched against that blob in exactly one commit |
| Image (for this run) | `harbor.arcadia-ecs.local/aiplayermod/agent@sha256:5f34afe403d989a58cbdf8a076415a4d6d5cb35ffa00f5c7a7b349a9444fff5b` (tag `2026-11-12-5d76c6f`) | three independent reads agree, all `sha256:5f34afe403d…`: the push output, Harbor's `Docker-Content-Digest` for the **OCI image index** (HTTP 200 from `/v2/…/manifests/`+tag with `/etc/docker/certs.d/…/ca.crt`), and `sha256sum` of that manifest body. Inside the pushed image: `script_tick.py` sha256 `51eecb6874f9edad8af9d1e5a8b5216cde7e7debf7eceb87e3df13643ed5942` (unchanged from the previous pin) and `agent.py` sha256 `97022b9118d531f1b8fb52995276b6028b7027883e327d411e990cd3555c7a88`, both equal to their hashes at `5d76c6f`; `scripts/` absent; the **module-level `bound_script_path` door** present (§8.3.1d). Known nit, not a blocker (FIXED since, at `28ec7d1`: the `Dockerfile` now runs `rm -rf ./tests && rm -f ./test_*.py ./*_test.py`, and run 4's image was verified to contain none). | see §8.3.2 step 0: take Harbor's `Docker-Content-Digest` for the OCI image index; never a local image ID, and never a value typed rather than pasted |
|   — built from | `5d76c6f` — fixes the run-1 dispatch failure: the param filter at `agent.py` no longer drops the caller's `type` key (the callee names that parameter `directive_type`, `api.py:428`), admits it explicitly, and renames to the callee's spelling at the splat inside `_run_directive`. Verified by review `a91cfdc` (PASS) on the production path, with the reviewer's own mutant reddening the suite. Build context `agent/`. | the pre-fix images `sha256:1c7d1f1c…9980` (tag `2026-11-11-3230926`) and `sha256:1b74ae7b…9506a4` (tag `2026-11-11-bf94724`, `bf94724`) are **dead** for this run — the first drops `type` and TypeErrors on every L3 directive (run 1, 2026-11-12), the second predates the `contract_version`, runner-token, bindings and `SCRIPTS_DIR` fixes |
| Pods | 1/1 `aibot-agent-test` | `kubectl -n minecraft-test get pods` |
| ConfigMap `agent-scripts` | **absent** | `get cm` → NotFound |
| Deployment volumes | `agent-data` PVC only — no script mount | manifest + live |
| Deployment env | `NN_COMPRESSOR_URL` only; **no `SCRIPT_RUNNER_URL`** | live env |
| Runner service | `agent-script-runner:8080` reachable in-namespace | `get svc` |
| Scout profile | image file `profiles/scout.json`, **no `script` key** | `exec cat` |

### 8.3.1a What already happened on TEST (2026-11-11), and what it invalidates

The rows above describe the cluster as it must be for the reviewed run. It did
not get there in one step, and the detour matters to anyone reading §8.3.5.

**A build of `ef8680b` was deployed to TEST at ~13:34Z and rolled back at
~13:41Z, without the review the lead had ordered.** The order was review, then
image, then plan delta, then review, then the lead's OK; the image went out
after the first review and before the delta. Rollback restored:

- image `agent@sha256:9de2a68c…142baf` (the same value as *Image (currently
  deployed)* above — read from Harbor's `Docker-Content-Digest` for tag
  `2026-11-05-c193f76`; note a first rollback attempt used a **typed** digest
  that was wrong and left the pod `InvalidImageName`, so the value here is the
  registry's, not a transcription);
- the mount/env patch reverted by strategic-merge delete, dry-run first:
  `env` back to `NN_COMPRESSOR_URL` alone, `/srv/aibot-scripts` mount gone,
  `agent-bot-data` PVC (`agent-data`) intact;
- ConfigMap `agent-scripts` deleted.

Verified after rollback: 1/1 Ready, `All 5 bots started (tick=2.0s)`, and
**zero** `[Bot/script]` lines in the agent log.

**What that invalidates.** Run 2 — the script-arm of the comparison — never ran
a tick the runner accepted. Every attempt was refused at the contract gate
(`contract_version` absent, then the 409 path), so `_run_script_tick` returned
`False` and **the planner took the tick, exactly as in the control run**. The
control arm and the script arm were therefore the same code path. Any §8.3.5
row that reads a *difference* between the two arms is reading run 1's numbers
or nothing at all, and must be discarded rather than reconciled. The run-2
observations are diagnostics: they found two real defects (§8.3.1b) and are not
milestone evidence.

### 8.3.1b Defects found by the unstaged run, and their fixes

Recorded here so the next operator does not rediscover them from a 409:

1. **`contract_version` was never sent.** The runner refuses any body whose
   `contract_version !== 1` *before* routing (`agent-script-runner
   src/server.js:151`). Fixed in `ef8680b`.
2. **The test that should have caught (1) was anchored on the wrong side of
   the boundary.** It scraped `handleTick`'s destructuring out of `main.js` —
   the handler that runs only after a request is accepted. It could not see the
   gate. Now the test scrapes every `body?.<field>` gate out of `server.js`, so
   a new runner gate fails it with no edit here.
3. **`SCRIPTS_DIR` unset fell back to the image's baked `bindings.json`**, so a
   failed mount ran a stale script that looked healthy. Fixed in `01e9eaf`:
   the resolver refuses and says so, and the Dockerfile no longer ships
   `scripts/`.
4. **The profile `script` key did not survive a pod restart** (emptyDir +
   `cp -an` seeding). This is why bindings live in the ConfigMap.

Scout must therefore be given the script **and** the runner URL, or the script
path is dead on arrival: `_get_script_tick` returns None without `script`, andthe transport falls through without `SCRIPT_RUNNER_URL`.

**The other four bots are unaffected, and here is why that is a fact rather than
a hope** (reviewer's finding, review `4432c6b`). All five bots share one process,
so "Scout only" has to be established per bot, not asserted:

- `agent.py:2639` reads `self.profile.get("script")`. `axiom`, `forge`,
  `mystic`, `tiller` have no such key (verified: grep for `"script` across
  `agent/profiles/` returns nothing), so `_get_script_tick` returns `None` for
  each of them, every tick.
- `_run_script_tick` returns `False` on a `None` tick **before** touching
  `_run_directive` or the loop's control flow, so their ticks take the L1/L3
  path byte-for-byte as before.
- The one change every bot *does* see is **not from M2**. `HEALTH_TIMEOUT`
  goes through `_float_env` (`6973c24`, 2026-11-04 04:41Z), which is **not an
  ancestor of the deployed `d45751d`** (04:39Z) — it is a two-minute-later commit
  that this image carries for the first time, along with the other 145. It
  changes a crash-at-import into a fall-back-to-default; the env is unset here,
  so the value is `10.0`, identical to today. Safe, but it is a passenger on
  this image, not part of the change under test.
- `SCRIPT_RUNNER_URL` is process-wide and newly set by this plan, but an unset
  tick is never built for a bot with no `script`, so it is read by nobody there.

### 8.3.1d The pin that named a rev without the function the plan calls

The previous pin in this table was `a97ae5a7`, built from `3887e79`. The plan's
own §8.3.3 step 2 tells the operator to run
`python3 -c 'import agent; print(agent.bound_script_path("Scout"))'` against the
pod. `3887e79` does not define `bound_script_path` — counted directly,
`git show 3887e79:agent/agent.py | grep -c 'def bound_script_path'` is **0**;
at `3230926` it is **1**. The plan instructed the operator to call a function
that was not in the image it instructed them to deploy.

**How it happened, because the mechanism will recur.** The pin was written when
`3887e79` was the head *of the code being fixed*. Then the door was added, and
the plan's step 2 was edited to use it, in commits that came after the build.
Each artefact was internally correct and reviewed in its own round: the image
matched its rev, and the run step matched the code at head. Nothing compared
*the rev the image was built from* against *the rev the run steps were written
against*. A pin is a pairing between two artefacts, and it has to be re-checked
as a pairing whenever either side moves — the same shape as the stale rev/hash
pair caught at §8.3.4, and the same reason a value sweep cannot find it.

**The gate this adds:** before re-pinning, run every `python3 -c` and every
command in §8.3.3 on the *image being pinned*, not on the worktree. A command
that works at head and not in the image is exactly this defect.

**What a reviewer can and cannot check here (reviewer, 15:2xZ, stated once).**
Every cluster-side figure in this section and in the run plan — the counts, the
mtimes, the pod start times, the `bound_script_path` grep at each rev, the file
hashes inside the image — was produced on my seat. A reviewer reading the plan
can verify its internal consistency and the shape of an argument, but not those
numbers, and should not be read as having verified them. Where a figure decides
whether a step is safe, the run re-checks it at execution time rather than
trusting this text; §8.3.2 step 0 and the §8.3.5 table are written that way on
purpose.

### 8.3.2 The change, in three parts

0. **Image** — build a new agent image from the reviewed head and push it. The
   deployed image (`d45751d`) predates every M2 commit, so it cannot run this
   step at all. Pin the pushed **index digest** into §8.3.1 before the rollout;
   a tag is not a pin (deploy rights require the digest, and a local image ID is
   not reproducible).

   **The build context is `agent/`, not the repo root** (found the hard way,
   13:15Z): `docker build -f agent/Dockerfile -t <tag> .` fails at
   `COPY requirements.txt .` with `"/requirements.txt": not found`, because the
   Dockerfile's paths are relative to `agent/`. The command that works is

   ```
   docker build -f agent/Dockerfile -t <tag> agent/
   ```

   Nothing in the failure is M2-specific — it is the same on any commit — but
   the operator runs this build, so it belongs here rather than in a message.

   **The new image carries far more than M2, and that must be said plainly**
   (reviewer, 12:53Z). The deployed image is `d45751d` (2026-11-04 04:39Z);
   `HEAD` is **167 commits** ahead of it at the run image's `3887e79`. Those commits contain work
   by other seats and other tasks, not only `coded-agents`. Two consequences:

   - **Do not describe the image step as "shipping M2".** It ships 167 commits,
     of which M2 is a subset. If the run goes wrong, the cause is not
     automatically M2, and the rollback returns the *whole* image to
     `d45751d`, not just the script path.
   - `_float_env` (`6973c24`, 2026-11-04 **04:41Z**) is **2 minutes after**
     `d45751d` and is therefore **not** in the deployed image. It is a
     pre-existing, post-deploy change that this image would carry for the first
     time. Earlier text in this plan called it "cosmetic-in-normal-use" as if it
     were part of M2; it is not M2, and it does change what the new image
     contains for a misconfigured pod. It stays safe (the env is unset here), but
     it is a passenger, not a deliverable.
1. **ConfigMap** — apply `deploy/agent-scripts.yaml`. It carries **two** keys:
   `scout.js` (generated from `agent/scripts/scout.js`) and `bindings.json`
   (generated from `agent/scripts/bindings.json`). The drift test keeps both
   equal to their sources. A ConfigMap with only `scout.js` is the 13:34Z
   failure in §8.3.1a: the mount exists, nothing binds, and no bot runs a script.
2. **Mount + env** — add to the container:
   - `volumeMounts: [{name: scripts, mountPath: /srv/aibot-scripts, readOnly: true}]`
   - `volumes: [{name: scripts, configMap: {name: agent-scripts}}]`
   - `env: [{name: SCRIPT_RUNNER_URL, value: "http://agent-script-runner.minecraft-test.svc.cluster.local:8080"}]`
   - `env: [{name: SCRIPTS_DIR, value: "/srv/aibot-scripts"}]` — **required**.
     Unset, the resolver used the image-local copy; the C1 fix (01e9eaf) makes
     that a loud refusal rather than a silent bind, but the scripts still do not
     run. Both the mount and this variable are needed, and neither is enough alone.
   - `env: [{name: RUNNER_TOKEN, valueFrom: {secretKeyRef: {name: agent-script-runner-token, key: minecraft}}}]`
     — the runner refuses every contract call without it. Found by running, not
     by reading: the code has no token at all before `f17fc10`, so the first
     real tick returned 409 and the agent fell back. Never print this value.
   - `env: [{name: PROFILES_DIR, value: "/srv/aibot-profiles"}]`
   - the `/srv/aibot-profiles` initContainer seed described in part 3.

   **The mount target is `/srv/aibot-scripts`, not `/opt/aibot-agent/scripts`**
   (reviewer, 12:53Z; verified against `agent/Dockerfile`). The Dockerfile ends
   `COPY . .`, so the build context's `agent/scripts/` already lands at
   `/opt/aibot-agent/scripts/` **inside the image**. Mounting a ConfigMap over
   that path would shadow the directory the image ships — the mount would appear
   to work while the image's own copy vanished, and the two would silently
   disagree about which file is live. A separate path keeps "shipped in the
   image" and "mounted from a ConfigMap" visibly distinct.

   Consequently Scout's `script` path — in part 3 and in §6 above — is
   `/srv/aibot-scripts/scout.js`.
3. **Bindings, not a profile key** — `agent/scripts/bindings.json` maps a bot
   name to a script file: `{"Scout": "scout.js"}`. With `SCRIPTS_DIR` set, the
   resolver reads that map and binds only the bots named in it. Every other bot
   resolves to no script and keeps the planner exactly as today.

   **Why not `"script"` in Scout's profile.** That was the original design and it
   failed twice on TEST (2026-11-11, §8.3.1a):

   - Profiles live in the **image** (`os.path.dirname(__file__)/profiles`). The
     `agent-data` PVC mounts `/opt/aibot-agent/data` only, and
     `/opt/aibot-agent/data/profiles/` does not exist, so the "edit the PVC
     copy" step the plan once had was a no-op — nothing the loader reads would
     have changed.
   - The image copy is read-only to a running pod, so the fix was an `emptyDir`
     at `/srv/aibot-profiles` seeded by an initContainer. But an `emptyDir`
     survives a container restart and not a pod recreation, so **any restart
     silently reverted the edit** and the run became a test of the stock
     profile. The `cp -an` seed kept the first edit but not the second.

   Bindings remove the problem instead of managing it: the map is a ConfigMap
   key, versioned in the repo, applied and rolled back like everything else. No
   profile is edited, so nothing is lost on a restart. `PROFILES_DIR` and the
   initContainer seed remain in the plan (parts 2 and 3 of the manifest) because
   they are already deployed and harmless, but **no run step depends on them**.

### 8.3.3 Order, and why

1. Apply the ConfigMap **without `bindings.json`** — i.e. only `scout.js` — and
   patch the Deployment (image + mount + env incl. `SCRIPTS_DIR` and the token).
   With no bindings map, `SCRIPTS_DIR` points at a directory with no map in it,
   so nothing binds and script mode is off: **the restart changes no behaviour**.
   The mount, `SCRIPTS_DIR` and the token are all present and provably inert, so
   the restart's risk is paid at a moment when the feature cannot act.
2. Confirm 1/1, that `scout.js` is in the mounted dir, and — the check that
   matters — that the resolver binds **nobody**:
   `python3 -c 'import agent; print(agent.bound_script_path("Scout"))'` → `None`.
   (`bound_script_path` is the module-level door added for this plan. The
   resolver itself is `BotRunner._bound_script_path`, an instance method — a
   plan line calling it off the module raises `AttributeError` at exactly the
   moment an operator is deciding whether the deployment is inert or quietly
   running the wrong file, which is a bad time to discover a typo. The door
   delegates rather than reimplements, and
   `test_the_module_level_door_agrees_with_the_method_in_every_state` holds the
   two in agreement across bound, unbound, no-file and the C1 refusal.)
3. **Run 1, the control** (§8.3.4). The planner handles the goal; the runner
   must see no tick.
4. Add `bindings.json` to the ConfigMap and restart. With the map present the
   resolver binds `Scout` only; every other bot still returns `None`.
5. **Run 2, the real run** (§8.3.4). Same goal, same everything else.

### 8.3.4 The negative control

The proof is worthless without one: a bot that happens to store something while
the script is loaded proves nothing. Both halves are required, in this order.

- **Run 1 (control):** bindings absent, so no bot runs a script. Drive the same
  goal and record whether any `STORE_ALL` POST reaches the mod. Expected: none
  from the script path (the planner may still emit one — that is the baseline
  to compare against, not a failure).
- **Run 2 (script):** same goal, `bindings.json` present and `SCRIPTS_DIR` set.
  Record the runner's action, the agent's applied `seq`, and the mod's POST
  response. **Confirm first that the two runs differ in the log**: run 1 must
  show no script line at all, run 2 must show the tick reaching the runner. If
  both show none, the comparison is meaningless and the run is void — that is
  exactly what happened at 13:34Z (§8.3.1a).

The control must **never stop the runner** (lead, 11:37Z) and must cut Scout off
agent-side only — the shared runner serves other work.

**How to drive the goal.** Not rcon, and not `/api/directive` (that sets a
directive directly and skips the tick the script is consulted on — it proves
nothing about §8.2). Use the mod's own chat injection, which is the same path a
player's line takes:

```
kubectl exec -n minecraft-test deploy/aibot-agent-test -c agent -- \
  python3 -c 'import api; print(api.inject_chat("Scout","OperatorTest","Scout, please store all your items in the nearby chest."))'
```

`inject_chat` posts to the **mod** API and needs the mod's key; in-pod `api`
already holds it (`api.API_KEY`), so run it inside the container as above and do
not put the key on a command line. Read it from the module, never print it.

The message lands in Scout's chat inbox, `_chat_poll_loop` drains it, and
`_maybe_plan` routes it to the L3 orchestrator (it logs
`[Scout/orchestrator] L3 plan layer accepting: ...`). Addressed-by-name is what
routes it: **include the bot's name in the text.**

**Run 1 result (control, measured 13:23–13:25Z at `46629e9`).** Injected the
goal shown above. Observed:

| observed | value |
|---|---|
| `[Scout/orchestrator] L3 plan layer accepting` | present (13:23:54Z) |
| `[Scout/orchestrator] starting plan for` | present |
| runner log lines before → after | 78 → 78 (no change — but this is **vacuous**, see below) |
| runner lines matching `scout` | 0 |
| `STORE_ALL` in the mod log | 0 |
| **script ticks in the agent log** (`[Scout/script]`) | **0** — this is the control that means something, because the agent logs every tick attempt whereas the runner logs none |

**The runner-log rows above prove nothing, and must not be cited as a control.**
`agent-script-runner/server.js` logs only startup, shutdown and errors, so
"runner log lines before → after 78 → 78" would read 78 → 78 whether the agent
sent zero ticks or a thousand. Measured on 2026-11-12: a tick that reached the
runner and executed (revision `823920fd` came back in the response) wrote no
line at all. A control that cannot move is worse than an absent one — it looks
like evidence. The script-tick line above is the real one.

The zero is a measured absence, not a dead grep: in the same window the mod
logged `[Scout] cancelDirective called` and `[Scout] HTTP DELETE /directive
(id=-1)`, so the detector was live and naming Scout. **Baseline established:
with no `script` key, the planner runs and the runner is never contacted.**

**What the planner actually does (this is run 2's bar).** It dispatched a real
directive, first subtask of three:

```
[Scout/L1] Directive sent: WIDE_SEARCH {'target': 'minecraft:chest'} -> accepted (id=1)
[Scout/L1] Wide search for minecraft:chest — moving to cell 1/25 (phase=pathing_to_cell)
```

Re-checked after that dispatch at 13:26:00Z: the runner still showed 78 lines and
0 Scout references. So the baseline is not "the planner was idle" — it is **the
planner did real work and the script path was never in it.** Run 2 must show the
runner receive a tick that the control never produced.

**The 78 is dead (lead, 15:31Z).** It was measured at 13:26Z. The agent pod has
been up since 13:39Z without restart and by 15:27Z carried **337** lines, so the
control's line count describes a two-hour-old process. Comparing run 2 against
78 would compare against a number nothing produces any more.

So the baseline is **re-taken immediately before run 2**, not quoted from above.
The command, and what each figure is for:

```
P=$(kubectl -n minecraft-test get pod -l app=aibot-agent -o jsonpath='{.items[0].metadata.name}')
L=$(kubectl -n minecraft-test logs $P -c agent)
printf '%s\n' "$L" | wc -l                    # total, for "did anything append"
printf '%s\n' "$L" | grep -c 'Scout/script] dispatch:'   # MUST be 0 before run 2
printf '%s\n' "$L" | grep -c 'Scout/script] not executed:' # MUST be 0 before run 2
printf '%s\n' "$L" | grep -c 'script tick'    # MUST be 0 before run 2
```

**Do not gate on bare `Scout/script` (found 04:19Z 11-12).** The resolver
prints `[Scout/script] no bindings at /srv/aibot-scripts/bindings.json; this bot
runs the planner` on every start of a planner-mode bot. On a correctly inert pod
that is **1**, not 0, so the old `grep -c 'Scout/script' # MUST be 0` failed on
a healthy run and would have been "fixed" by loosening a check that was right.
Gate on the two behaviour lines (a `dispatch:` or a `not executed:` line) or on
`script tick`; the bracket tag alone matches the resolver's own status line.

Measured 15:27:26Z: 337 lines, `dispatch:`/`not executed:` **0**, `script tick`
**0**. The two zeros are the ones that matter; the total is only a cursor. (The
`Scout/script` tag itself read 1 on the healthy 04:19Z pod — see the hazard note
below the command.) **Count the
behaviour, not the bot's name:** `grep -ci scout` returns 52 on this log and
every one of them is unrelated (profile discovery, a fleet respawn, and 47 HTTP
connection-pool retries written while the Minecraft server restarted for the
rcon rotation). A name count would have been read as script activity; it is not.

**Baseline hazard, stated once.** Those 227 pool errors are still in the log.
Run 2's diff must be taken on the `Scout/script` and `script tick` lines, never
on total line count alone, or a burst of connection noise will look like
script-path activity. The agent recovered cleanly at 15:25:01Z (schema re-push),
so the errors are historical, not ongoing.

### 8.3.5 Verification, per piece

Every row below names a line the code **actually prints or sends** (reviewer,
12:53Z; each verified at the rev). An earlier draft asked for an agent `seq`
line and a ConfigMap-sourced revision; the agent prints no `seq`, and the
revision is hashed from the script body, not carried in the ConfigMap.

| # | Evidence | Failure looks like |
|---|---|---|
| 1 | **Tick response** (not the runner log): the tick carries `bot_id: "Scout"`, `script_revision: 823920fd7277b98b`, non-empty `actions` | a tick that returns no revision, or one that never reaches the runner → the tick never left the agent. Read it from the RESPONSE, because `agent-script-runner/server.js` logs only startup, shutdown and errors — a successful tick writes **no runner log line at all** (measured 2026-11-12; corrected here after run 2). The revision value is **measured**, not derived: on the live pod, `sha256sum /srv/aibot-scripts/scout.js` returns `823920fd…a512` at 3526 bytes, identical to the source file (the ConfigMap round-trip is byte-exact) |
| 2 | **Agent** log: `[Scout/script] dispatch: STORE_ALL {...}` present, and **no** `[Scout/script] not executed:` line (see note: the success return is **not** in the agent log) | the `dispatch:` line never appears → the action was refused before dispatch; a `not executed:` line → the orchestrator returned FAILED and that action did not run |
| 3 | Mod POST response: `status: accepted`, `STORE_ALL`, **coordless** | coordinates present → §3's pin is wrong, record it |
| 4 | Run 1 produces no script-path POST | a POST with no script → something else is emitting it |
| 5 | **The in-flight guard fired**: with a directive genuinely running (`task.progress.phase` not `"idle"`), the tick emits **no** `actions` for that bot, and the agent log shows neither `dispatch:` nor `not executed:` | non-empty `actions` → the guard did not fire; a `not executed:` line → the guard did not fire and the action was refused downstream instead |
| 6 | **The low-health guard fired**: with Scout damaged below 8 hp, the tick carries **no** `actions`, and the agent log shows the `too low` line | `actions` carrying `STORE_ALL` → the guard did not fire (this was the live defect until `d75f30b`) |

**Row 5 is not satisfied by row 2's absence-of-refusal.** Those look identical
in the log and mean opposite things. Row 2's clean case (dispatch happened,
`COMPLETED`) and row 5's case (nothing attempted) are both "no `not executed:`
line", so the pass condition for row 5 is the **absence of `actions` in that
bot's tick for that tick**, read from the tick response, not the absence of a
refusal line in the agent log. (It was "read from the runner log" until
2026-11-12; the runner emits no per-tick line on success, so that form could
never be satisfied and would have read as a permanent failure.)

This row exists because the guard was dead twice over, and the first fix was
not enough. `scout.js` opens with `if (snapshot.task) return []`, and
`SnapshotCache.get` built the envelope without `task=`, so `envelope["task"]`
was `None` on **every** tick and the guard could never fire (reviewer, 13:03Z;
`snapshot.py:144` fixed the PLUMBING). But with `task=` wired up, `task` holds
`api.get_directive()`, which returns an idle bot as an OBJECT —
`{"state":"Standing by","progress":{"phase":"idle"}}` — never `None`. So the
truthiness guard fired on every idle tick too, and the script proposed nothing
at all (run 2, 2026-11-12). The guard now reads
`task.progress.phase === "idle"`, and the fixtures are copied from the real
idle and busy responses rather than constructed. Under the old code
the first branch ran even with a directive in flight, the action was refused
downstream as `already-has-a-directive`, and the run would have shown a
`not executed:` line — a refusal, which reads as the system working, rather than
a guard that never fired. §1's third scenario was unmet and the evidence could
not have shown it.

**Why row 2 does not require a success line** (reviewer, 13:11Z; verified here).
`_run_script_tick` prints the dispatch result **only when it starts with
`FAILED`** (`agent.py:2647`); the success string is pushed to telemetry
(`agent.py:1025` → `telemetry.py:37`, a POST to `MOD_API_URL/telemetry/event` on
a daemon thread) and never reaches the agent log. Grepping the suites for both
strings returns six `dispatch:` lines and zero `COMPLETED`. So an operator
running the original row 2 would have found `dispatch:` and no `COMPLETED`,
concluded the action was refused, and recorded a failed run against working
code. The two surviving clauses already separate the three cases: `dispatch:`
present distinguishes ran from refused-before-dispatch, and a `not executed:`
line distinguishes dispatched-then-FAILED. If the success return is wanted, it
is telemetry, and §8.3 names no telemetry reader — so it is left out rather
than cited from the wrong surface.

**Why row 6 does not require a log line** (reviewer, 13:10Z; verified here). The
script does produce `scout: health N too low, holding`, but `api.log` is not an
action: it rides the tick as the wire `logs` field, and `tick()` returns
`(handled, actions, refusals, detail)` — `logs` is in none of those, and a grep
of `agent/` for a reader of it finds only the Minecraft item name `"logs"`.
Nothing in the agent prints it, so a correctly-firing guard would go red against
a correct fix — and a red row here invites the conclusion that the guard is
broken, which is the exact confusion row 6 exists to prevent. The
absence-of-a-runner-tick condition already separates a firing guard from a dead
one, for the same reason it does in row 5. Plumbing wire `logs` into the tick
tuple and all its callers is a real change and belongs in its own slice, not
this gate.

**Why row 2 exists as its own line.** `agent.py` used to read `act["directive"]`
from the *bound* action, get `None`, and `continue` — printing
`N action(s) this tick` for actions that executed nothing (reviewer, 12:53Z;
fixed). The `dispatch:` line is printed only for an action that reaches the
dispatcher, so its presence is the check that binding→dispatch actually
happened. `N action(s) this tick` alone is **not** evidence and must not be
cited as such.

**Dispatch goes through `_l3_orchestrator_dispatch`, not `_run_directive`**
(reviewer, 12:57Z). `BINDABLE_KINDS` is the mod's 35 plus the agent's 10, and
the agent-side ones are not mod directives: `EQUIP`/`EQUIP_ALL` map to
`api.equip_all`, `DROP`/`DISCARD` resolve an item to inventory slots, and
`VAULT_STORE`/`STORE`, `VAULT_WITHDRAW`/`WITHDRAW`, `PROVISION_TERMINAL` and
`ASK_PLAYER` are all special-cased in the orchestrator (`agent.py:901`).
Posting those straight to the mod fails. Worse, the earlier version returned
`True` even when an action failed, so a refusal **consumed the tick** and the
planner never ran — a bot that asked for impossible work would have gone
silent. The orchestrator handles both vocabularies and returns
`COMPLETED`/`FAILED` without raising, which is also how the tick learns whether
anything actually ran: a tick whose actions all returned `FAILED` falls through
to the planner. This does not endanger the step-4 run, whose script sends
`STORE_ALL` only — a genuine mod directive — but it had to be settled before a
second script exists.

**Row 1's revision is computed at runtime, and it equals the source file's hash
— measured, not assumed.** `_revision_of` (`script_tick.py:58`) hashes the bytes
`_get_script_tick` (`agent.py:2676`) reads with `open(path).read()`. On this run
that path is the mounted ConfigMap, so the question is whether the mount is
byte-equal to `agent/scripts/scout.js`. On the live pod it is:

```
kubectl -n minecraft-test exec deploy/aibot-agent-test -c agent -- \
    sh -c 'wc -c < /srv/aibot-scripts/scout.js; sha256sum /srv/aibot-scripts/scout.js'
3526
823920fd7277b98bb167012680723d7c5e917ac70f7567a4771a447ddb97a512
```

3526 bytes and `823920fd`, identical to the source file and its git blob. The
ConfigMap round-trip is byte-exact despite `gen-scripts-cm.py`'s
`text.rstrip("\n")`: YAML's `|` block scalar restores exactly the one trailing
newline the generator removed.

**A correction that was itself wrong, recorded because it nearly shipped.**
While preparing this step I "fixed" this row from `823920fd` to
`34965be5460dd62f`, reasoning from the ConfigMap's `data` value as returned by
the API, which the generator had stripped. That value is a real hash of real
bytes, but not of the bytes the agent reads — the volume materialises the file
with the trailing newline. The original value was right; the fix introduced the
error. The measurement above is what settles it, and it is the reason the row
now cites the pod rather than an argument.

Item 4 is the one that makes 1–3 mean anything.

Item 4 is the one that makes 1–3 mean anything.

### 8.3.6 Known hazards for the run

- **The runner URL is new code** (`4035605`): before this, the transport
  defaulted to `api._post` → `MOD_API_URL`, i.e. the tick would have gone to the
  game mod and silently looked handled. The run must show the request arriving
  at the *runner*, not merely an absence of errors.
- **Test invocation:** the M2 suites are run from `agent/`
  (`cd agent && python3 -m unittest …`). From the repo root they error —
  `agent/` has no `__init__.py`, so `unittest agent.test_x` resolves `agent` to
  `agent.py`. A CI runner invoking from the root would fail; the run plan says
  `agent/` explicitly for that reason.
- **The script map is a ConfigMap**, so it rolls back and reviews like any other
  manifest. Nothing the run depends on lives only on a pod.

### 8.3.7 What this plan does NOT claim

- It does not claim the planner emits coordless `STORE_ALL` in the wild. Two
  producers are known to (`agent.py:1888` bare, `SkillRegistry.java:154` bare);
  a raw model emission is untraced. Run 1 records the planner's real form.
- It does not claim the bot will store anything. The script may return early
  (low health, task in flight) — that is a fall-through to the planner, which is
  correct behaviour and would make run 2 look like run 1. If both runs match,
  check the AGENT log for `[Scout/script]` tick lines before concluding the
  feature failed — the runner writes no per-tick line, so an empty runner log is
  not evidence either way.

### 8.3.8 Run 4: the boundary translation, image and ConfigMap

Run 3 deployed the `api.do` fix and was refused one layer further on. Run 4
ships the translation that closes that refusal. Unlike run 3, **this change is
in agent code, which ships in the image**, so the run moves two things and must
be able to roll back both.

| What | Before (live, measured 05:32Z) | After |
|---|---|---|
| Agent image | `harbor.arcadia-ecs.local/aiplayermod/agent@sha256:d1513fa2d6ecab1b761fe692078e065b27324d8b05e15062380f55ed69da3f41` | `harbor.arcadia-ecs.local/aiplayermod/agent@sha256:a9e75ad1b1efd22f9cc15f81662aa0865d068e92c555f034a0440bd0c9147c38` (tag `2026-11-13-59f30a5`) — Harbor's `Docker-Content-Digest` for the OCI image index, matching the push output |
| `agent-scripts` ConfigMap, key `scout.js` | `838efd89…` (the rolled-back broken bytes) | `1824967e…` — the reviewed bytes at `6f8ad66`, 5852 bytes |

The image digest in the "before" column is confirmed two ways: the Deployment's
`spec.template.spec.containers[0].image`, and the running pod's
`status.containerStatuses[0].imageID`, which are equal. That equality is what
makes it a re-appliable rollback rather than a remembered value.

**Why both are needed.** `scout.js` rides in the ConfigMap and the translation
rides in the image. Deploying one without the other reproduces run 3's refusal
exactly: the fixed script emits `{seq, call, directive, args}`, and an image
without the translation refuses every record with `action has no 'kind'`.

**The image is proved against its rev before it is used.** Read inside the
built image, `sha256sum` gives `script_tick.py` `fd212211839f08b0…`, `agent.py`
`d765915655cf5e5a…` and `action_binding.py` `728825f7ab11351f…`, each equal to
`git show 513b502:<path> | sha256sum`. Equal hashes are what rule out an image
built from the wrong rev; a tag alone does not. The image also has no
`/opt/aibot-agent/scripts/` and no `test_*.py`, so the ConfigMap stays
authoritative for script content and the tests do not ship.

**Steps.**

1. **Build and push.** DONE: `docker build -t …/agent:2026-11-13-59f30a5` from
   `agent/`, with `DOCKER_CONFIG=~/.docker-minecraft`; digest read from Harbor
   for that tag, not from `docker images`.

   **Which rev the image ships.** The tag says `59f30a5` because that is the
   commit it was built at, and the tag is a record, not a claim to be rewritten.
   The *reviewed* rev is `513b502`, and the production bytes are byte-identical
   across `d9c1707`/`59f30a5`/`513b502` (reviewer 3a94d0c: `diff` of
   `script_tick.py`, `agent.py`, `action_binding.py`, `test_scout_script.py`
   between `59f30a5` and `513b502` is empty). The image was additionally
   verified to have been built from this tree: unzipped and hashed, its three
   files match `git show 513b502:<path>` exactly. The three hashes, so the
   check is re-runnable by someone who was not in the session:

   ```
   agent/script_tick.py      fd212211839f08b08f59962796afe1dc28f74cb18827a12e3879463229229443
   agent/agent.py            d765915655cf5e5ac52154009f3b81bfbe3a646f1692a5c34afe1c30a2e9d93d
   agent/action_binding.py   728825f7ab11351f3880b3c6cae10a0db00a11ac2bed6fa0626e5e800c5c7d89
   ```

   Each is `sha256sum` of the file at `513b502`; the same command run on the
   file inside the image gives the same three. Computed twice independently
   (builder and reviewer) and agreeing. That is what `:1485`'s rule asks for:
   equal hashes rule out an image built from the wrong rev, where a tag alone
   does not. So the shipped tree is `513b502` for every purpose that matters,
   and the tag's `59f30a5` names the build moment of the same bytes.
2. **Back up both live halves**, and verify each backup holds what it claims:
   `kubectl -n minecraft-test get deploy aibot-agent-test -o yaml` (expect the
   digest above) and the `agent-scripts` ConfigMap (expect `838efd89…`).
   Re-read the backup file's content and hash it; a backup is not a rollback
   until it has been read back.
3. **Apply the ConfigMap** from the reviewed rev, namespaced:
   `git show 6f8ad66:deploy/agent-scripts.yaml | kubectl -n minecraft-test apply -f -`.
   The file carries no `metadata.namespace`, and the default context's
   namespace is empty, so an un-namespaced apply lands in `default` and reports
   success while changing nothing that matters.
4. **Set the image** to the pushed digest on the Deployment (not `:latest` — the
   live object is digest-pinned, and leaving a tag there loses the record of
   what ran).
5. **One restart** picks up both, since `_script_loaded` caches once and never
   re-reads. Wait for the rollout, then confirm the pod is `Running` with 0
   restarts.
6. **Verify inside the pod, not just in the API:** the mounted
   `/srv/aibot-scripts/scout.js` hashes to `1824967e…`, and
   `/opt/aibot-agent/script_tick.py` inside the image contains
   `translate_runner_actions`. The second is the check that the image actually
   changed; the ConfigMap digest alone would pass on a stale image.
7. **Evidence.** The pass criterion is unchanged: a verbatim agent-loop
   `dispatch:` line for `STORE_ALL` carrying the matching `seq`, plus the
   mod-side effect. Silence or the absence of errors does not count.

**Rollback, both halves.** `kubectl -n minecraft-test set image
deploy/aibot-agent-test agent=<the before digest>` and re-apply the ConfigMap
from the backup. **Do not restore the Deployment from a `-o yaml` backup**: that
dump carries the `resourceVersion` it was taken at, and applying it later is
rejected as stale — the cluster keeps the new bytes while the next read still
looks plausible. That happened in run 3's rollback and was caught only by
re-reading the digest. `set image` takes a digest directly and carries no
version, which is why it is the form here.

**What would make this run uninformative rather than failed.** If the script
returns early on every tick (health below 8, or a task in flight), there is no
refusal and no dispatch, and the run says nothing about the translation. That is
not a failure — check the agent log for the guard's own line before concluding
anything, because a clean log with no dispatch is otherwise indistinguishable
from a working translation that had nothing to do.

---

## 9. Rollback

**Two different rollbacks, named so they cannot be confused.** Run 3 failed and
was rolled back to *planner-only* (§9 block below: ConfigMap deleted, so no bot
runs a script). Run 4's own rollback is different -- it restores the pre-run
state, which HAS a script bound to Scout, and is specified beside the run at
§8.3.5: `set image` to the before-digest plus re-apply the ConfigMap from
backup, so Scout keeps running the old `scout.js` through the old image. Use the
§8.3.5 one to undo run 4, and the block below to take the whole feature back
out. Deleting the ConfigMap is a deliberate step *away* from the pre-run state,
not a restoration of it.

No data migration and no schema change, so rollback is code-only:

```
# every line names -n minecraft-test: minecraft/aibot-agent is PROD (§8.3.0)
POD=$(kubectl -n minecraft-test get pod -l app=aibot-agent,tier=test -o jsonpath='{.items[0].metadata.name}')
echo "$POD"                                                      # must be non-empty before continuing

git revert <this change's commits>                               # agent-side only
# ConfigMap first, THEN the deployment. Deleting the ConfigMap is what stops
# script mode: _bound_script_path reads bindings.json from $(SCRIPTS_DIR), so
# with the ConfigMap gone it returns None and every bot falls back to the
# planner -- no restart needed for that, but the tick cache means the running
# pod keeps its loaded script until it restarts, which is why the rollout
# follows. (Corrected 2026-11-13: this comment used to say the previous pod
# spec has neither the scripts mount nor SCRIPTS_DIR. Measured, it has both --
# so the rollback cannot rely on the spec to disable scripts.)
kubectl -n minecraft-test delete configmap agent-scripts   # stop script mode
kubectl -n minecraft-test rollout undo deploy/aibot-agent-test
kubectl -n minecraft-test rollout status deploy/aibot-agent-test --timeout=180s

# verify the restore landed, not just that the commands exited 0:
kubectl -n minecraft-test get deploy aibot-agent-test \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}{.spec.template.spec.containers[0].env[*].name}'
# expect: the rollback digest, and all four env names in this order --
#   [NN_COMPRESSOR_URL SCRIPT_RUNNER_URL SCRIPTS_DIR RUNNER_TOKEN]
# This line used to say "exactly [NN_COMPRESSOR_URL]". That was true when the
# section was written, before the script wiring existed; it is false on the
# live object now (measured 2026-11-13), where `scripts` is already a mounted
# volume and SCRIPTS_DIR/RUNNER_TOKEN are already set. Run rollback does not
# REMOVE the script wiring -- it restores the previous pod spec, which has it.
# Follow the old text and a correct rollback reads as a failure.
kubectl -n minecraft-test get cm agent-scripts                          # expect NotFound
kubectl -n minecraft-test logs deploy/aibot-agent-test -c agent --tail=200 | grep -c '\[.*/script\]'   # expect 0
```

**No profile file is restored, because no profile is edited.** An earlier
version of this section copied `evidence/step4-scout-profile.before.json` back
over `/srv/aibot-profiles/scout.json`. That step is now deleted: with bindings
driving the run, the profile never changed, so the copy would exit 0 while
restoring a file nothing reads — the "silent no-op that reports success" shape
this rig has been bitten by before. The profile evidence files stay in the repo
as history of the abandoned design.

The rollback was exercised for real at 13:34Z (§8.3.1a) and the three commands
above are that sequence: `rollout undo`-equivalent patch, ConfigMap delete,
then the three reads. It left the deployment on the rollback digest with
`env=[NN_COMPRESSOR_URL]`, 1/1 Ready, five bots ticking and zero script lines.

The `rollout undo` line matters for the same reason the ConfigMap line does:
`rollout undo` reverts the Deployment to its previous pod spec, which no longer
references the ConfigMap, but **does not delete the ConfigMap itself**. Left
behind it is inert, but it is a stale script a later reader might mistake for
live. Delete it so the rollback leaves no artefact claiming to be active.

**The profile is not read for the script path, and this is the check that
settles it.** `_bound_script_path` (`agent/agent.py:2736`) resolves the script
by reading `<SCRIPTS_DIR>/bindings.json`; it never consults
`/srv/aibot-profiles/scout.json`. So deleting the ConfigMap removes the only
thing that pointed Scout at a script, and Scout falls back to the planner with
`bindings.json` absent — there is no "profile pointing at a missing path" to
restore, because no profile ever held the path. The emptyDir at
`/srv/aibot-profiles/` still exists and is still seeded by the initContainer,
but under the bindings design nothing reads the script field from it.

(An earlier version of this section restored the profile with `kubectl cp -c
agent`. Both halves of that are now gone: the `cp` because the profile is not
restored, and the `-c agent` qualification with it, since a copy that does not
happen has no container to name.)

After the rollback, verify: the pod is 1/1, `bindings.json` is absent, and
`kubectl logs ... | grep -c '\[.*/script\]'` is 0 — which together show the
bot returned to planner-only operation.

If the Deployment edit has not been applied yet (the ConfigMap is added but the
mount is not), deleting the ConfigMap is the whole rollback and `rollout undo`
is unnecessary.

The runner is **not** removed — it is deployed, verified and independent; the bot
simply stops calling it and uses the planner. That is a property worth stating:
the M2 change is additive and its failure mode degrades to the previous
behaviour, not to no behaviour.

---

## 10. Order of work

1. Tick 4.1/4.2/8.1 in `tasks.md` — **done**, commit `5f52a79`, corrected at
   `73fd81f`. Read the ticks at `73fd81f`: `5f52a79` records the superseded
   `416ef999` digest, which is now only the rollback target (reviewer 11:34Z).
2. Measure §1's snapshot latency on TEST (decides four-call vs new endpoint).
3. `script_client.py` + 4.3/4.4 tests (the bound and the fallback first, so the
   bot is never dependent on an unproven call).
4. Snapshot builder (3.1), then action binding (3.2) + its refusal test.
5. Parity (3.3): the two-layer comparison, first proof on the smallest real
   `DirectiveType` that crosses the binding. `MINE`/`CHANNEL`/`STORE_ALL` are
   later checks, not the first.
6. The first script + 8.2 proof, including the negative control.

Each step's tests run before the next. Gradle/agent tests: `-Xmx2g`
`--max-workers=2` `nice -n 19`.

---

## 11. Open questions for the reviewer

1. **§1's four-call snapshot**: agree that measuring before adding a mod
   endpoint is right, or is the aggregated endpoint obviously correct?
2. **§3.3 parity subject**: originally `say` — **subsequently found not to be a
   `DirectiveType`**; ruled at 12:14Z as a two-layer comparison on a real
   directive (see §3.3).
3. **§6 script storage in the agent image**: scripts ship in the agent image, so
   changing a script needs a rebuild. Acceptable for M2 (one hand-written
   script), but it is the thing that will hurt when 7.1 lands. Worth a ConfigMap
   now, or defer? — **ANSWERED: ConfigMap now** (below), and §6 has been
   rewritten to match; it no longer says the script lives in the image.

---

## Decided at review (2026-11-11 10:33Z)

The reviewer ruled on all three open questions. Recorded here so the plan does
not carry open items into implementation:

1. **§1 snapshot: measure first, and add no mod endpoint in M2.** All four calls
   are already made by the planner, so a short-TTL cache in `api.py` is
   agent-only work. Escalate to a mod endpoint only if the cache proves
   insufficient — and then as its own change, not folded into M2.
2. **§3.3 parity: two-layer comparison ruled at 12:14Z** — `say` is not a
   `DirectiveType`, so the subject is a real directive with the binding under
   test; the silence counter-case stands.
3. **§6 script storage: ConfigMap now, not deferred.** Deferring is the
   expensive choice, because re-proving 8.2 means changing the script and
   running the proof again; a baked-in script would need an **image rebuild**
   for every re-proof, where a ConfigMap needs an apply and a pod restart.
   **The restart is not optional, and there is no runtime toggle.** The agent
   caches the script on the first tick (`self._script_loaded`, `agent.py:2797`)
   and never re-reads it, so editing the ConfigMap on a running pod changes
   nothing — measured 2026-11-12: the ConfigMap was patched with
   `bindings.json` and the running pod logged `no bindings at
   /srv/aibot-scripts/bindings.json` for six minutes until it was restarted.
   Switching the script ON and OFF both take a pod restart. No rebuild, but not
   a live toggle either. The
   original rationale here said the control requires "stopping and restarting
   the runner mid-proof" — that is no longer true, since the lead ruled
   (11:37Z) that the control must never stop the shared runner and cuts Scout
   off agent-side instead. The decision stands on the rebuild cost alone. If a
   later change does bake scripts in, the rebuild cost must be stated, not left
   implicit.

---

## 8.4 The owed controls: run plan (written 2026-11-13; C2a and C2b executed 2026-11-13)

**Status (lead, rewritten 2026-11-17 from the primary records):**

| Arm | Status | Primary evidence |
|---|---|---|
| **C2a closed port** | **PASS**, 2026-11-13 | pod `vqs44`, agent image `a9e75ad1`: state `fallback_connect_refused`, 0 dispatches; evidence read 11:04:43Z, before the builder's unauthorised listener exec at ~11:11Z perturbed that pod (one stray `read timeout` line at 11:11, outside C2a's evidence window) |
| **C2b silent listener** | **PASS**, 2026-11-13 | listener accepts first 11:14:17Z, last 11:16:13Z (48 accepts); Scout logged 48 `fallback_timeout: read timeout` lines, 11:14:17.61Z to 11:16:13.82Z, all after the first accept; 0 `dispatch:` lines; the single `connect refused` line (11:14:15.20Z) precedes the first accept, i.e. C2a's window, so it does not void C2b |
| **C1 control** | **OWED — not executed** | the 2026-11-11 13:2xZ no-script run dispatched `WIDE_SEARCH`, not `STORE_ALL`, so it does not stand in for §8.3.4 Run 1 |
| **C4 script arm** | live since 2026-11-15 18:06Z | test pod `q49qp`, agent image `2914fb85`, Scout bound to `scout.js` (hashes as §8.4.3) |

C2a + C2b together discharge the negative control at `:841` (runner unreachable
for Scout only; the shared runner was never stopped). Only **C1** remains, and it
must follow §8.4.2 and §8.4.3 *as rewritten below*: the Deployment is no longer
paused.

**Image caveat.** C2a, C2b and run 5 (C4) ran on agent image `a9e75ad1`; C1 will
run on `2914fb85` (the replan fix). The C1 evidence (a `no bindings` line and
zero `dispatch:` lines) is a property of the binding resolver, which the replan
fix does not touch, so the arms remain comparable on what each is allowed to
prove (§8.4.8). Any comparison of *planner behaviour* across arms must say which
image each arm ran on.

§8.4.4 and §8.4.5 below are kept as the record of the executed C2 arms. Their
paused-Deployment steps describe the state on 2026-11-13 and do not apply to C1.

Original motivation (2026-11-13): ask 4 of `qitem-20261113100843` was answered
"not done" — the control arm (§8.3.4 Run 1) and the negative control had never
been executed as their own evidence, and the run-5 result is the script arm, not
a control. Cobblestone left in slot 0 is script behaviour (the selected-slot
trap), not a baseline.

### 8.4.0 What makes this plan necessary

§8.3.1a records a run where both arms were secretly the same code path — every
tick was refused at the contract gate, the planner took the tick in both arms,
and a difference was reported anyway. The controls exist so that cannot recur.
This plan therefore states, for each arm, **the log line that proves the arm is
the arm it claims to be**, and voids the run if that line is absent.

### 8.4.1 The four arms, and the one line that distinguishes each

| Arm | Configuration | The line that proves it | A run is VOID if |
|---|---|---|---|
| **C1 control** | no `bindings.json` (key absent) | `no bindings at /srv/aibot-scripts/bindings.json; this bot runs the planner` (`agent.py`, `FileNotFoundError` branch) → **no `[Scout/script]` action line at all** | any `[Scout/script] dispatch:` line appears |
| **C2a closed port** | Scout bound, `SCRIPT_RUNNER_URL=http://127.0.0.1:1` | state `fallback_connect_refused`, detail `connect refused: ...` (`script_client.py:169`) | the state is `fallback_timeout` — that is C2b, not C2a |
| **C2b silent listener** | Scout bound, `SCRIPT_RUNNER_URL` **unchanged** (`127.0.0.1:9`) with a listener bound to it in the same pod (§8.4.5.1) | state `fallback_timeout`, detail `connect timeout: …` or `read timeout: …` (`:165`,`:167`), **timestamped after the listener's first `accepted`** | any `connect refused:` after that accept (listener died mid-arm); or a timeout with **no** accept recorded; or a fallback line before the first accept (that is C2a's window) |
| **C4 script arm** | Scout bound, runner healthy | `dispatch: STORE_ALL seq=1` **and** the mod's accepted POST | no `dispatch:` line (this is what the 05:57Z regression looked like) |

C2's two sub-cases are distinct and §8.3.4 requires both: a **closed port**
(`127.0.0.1:1`, immediate refusal) tests the error branch; a listener that
**accepts and never replies** tests the bounded wait. A refused connection
cannot exercise a missing timeout, so passing only the closed port proves
nothing about 4.3.

### 8.4.2 The constraint that shapes every step

Per §6's ruled decision (2026-11-11), **the agent caches both the bindings and
the script source for the life of the pod** — `self._script_loaded` at
`agent.py:2804`, and `self._source` captured at `script_tick.py:236` and resent
every tick at `:282`. Measured 2026-11-12: a ConfigMap patch on a running pod
changed nothing for six minutes.

Therefore **every arm transition requires the pod to be recreated.** This is not
a convenience detail: a plan that edits the ConfigMap and reads the log without
recreating the pod will observe the *previous* arm and record it as the new one
— a false pass in the exact shape §8.3.1a warns about.

**Not by `rollout restart`.** *(Updated 2026-11-17.)* When this was written,
`deploy/aibot-agent-test` was paused and refused `rollout restart`. It is **no
longer paused** (live 2026-11-17 10:2xZ: `spec.paused` unset, strategy
`Recreate`; the pod template still carries the inert annotation
`m2-step4: step1-inert` and a `restartedAt` of 2026-11-13T05:16:47Z). Pod deletion
is still the procedure, for a different reason: `rollout restart` writes a new
`restartedAt` into the template, which makes a new ReplicaSet, and a later
server-side apply of the manifest would then own and delete those undeclared
template annotations and roll the pod again (reviewer, `REVIEW-0c4b52b-gen-bump.md`
in the manifests repo). **Deleting the pod** recreates it from the *same*
ReplicaSet and template, so the only thing that changes between arms is the
ConfigMap. Every transition in §8.4 therefore uses:

```
# THE ONLY permitted recreation procedure. Runner untouched.
kubectl -n minecraft-test get pod -l app=aibot-agent,tier=test \
  -o jsonpath='{.items[*].metadata.name}'        # OLD pod name(s)
kubectl -n minecraft-test delete pod <old-pod> --wait=true
kubectl -n minecraft-test get pod -l app=aibot-agent,tier=test \
  -o jsonpath='{.items[*].metadata.name}'        # NEW pod name -- must differ from OLD
kubectl -n minecraft-test wait --for=condition=Ready pod/<new-pod> --timeout=180s
```

**Proof the recreation took effect, required before reading any arm evidence** —
both conditions, not either:

1. **New pod name** differs from the old one, and
   `.status.startTime` on the new pod is later than the delete.
2. **A fingerprint read from inside the new pod** matches the arm just applied:
   `kubectl -n minecraft-test exec <new-pod> -c agent -- sha256sum /srv/aibot-scripts/bindings.json /srv/aibot-scripts/scout.js`
   (`-c agent` is required: without it kubectl prints a
   `Defaulted container "agent" out of: agent, seed-profiles (init)` warning
   into the captured evidence)
   (`annotate` the two hashes, never print the script or the map). A bindings
   change that is not visible in the *new* pod's mount means the ConfigMap patch
   did not land, and the arm is void.

**Do not change the Deployment template during a control run** (no `set image`,
no `rollout restart`, no manifest apply). Any of these makes a new ReplicaSet and
measures a different deployment than the one the arms compare; an image or
manifest change is a separate lead decision with its own plan. *(This replaces
the 2026-11-13 rule "do not resume the Deployment", which no longer applies: the
Deployment was unpaused before 2026-11-15 18:06Z, when pod `q49qp` started.)*

⚠ **`bound_script_path()` is not evidence that an arm took effect.** It does
`BotRunner.__new__` and reads `bindings.json` **fresh** (`agent.py:3850`), so it
answers *what a new process would bind*, not *what the live bot is running*. A
step that used it to confirm a binding change without recreating the pod would
read the new config while the bot still served its cached script — the exact
false pass this section exists to prevent. Its use at §8.3.4 `:1179` is *before*
the restart and is correct there; this section's evidence is the log, read from
the new pod.

Two things that are *not* required, to keep the blast radius small:

- **The shared runner is never stopped or restarted** (lead, 11:37Z): cardgame
  calls it from their own test account.
- Only the agent pod is deleted. `replicas=1`, so this is a brief gap in Scout's
  ticks and every other bot's; that gap is the cost of the control and is
  accepted by the lead's delete-pod ruling.

### 8.4.3 Preconditions (read-only; abort if any fails)

**Live baseline, measured by the lead 2026-11-17 10:2xZ (read-only):**

| item | value |
|---|---|
| test agent pod | `aibot-agent-test-fc9f559cb-q49qp`, started 2026-11-15T18:06:02Z, 0 restarts |
| test agent image | `agent@sha256:2914fb85ff22…` (template and running pod agree) — the replan fix `ca27b6e`, same as prod |
| `spec.paused` | unset (not paused); strategy `Recreate` |
| runner | `agent-script-runner@sha256:e07a90c56537…` (shared with cardgame; never stopped by this plan) |
| ConfigMap `agent-scripts` | `scout.js` `1824967e200dab94` / 5852 B; `bindings.json` `10cef1b830853225` / 26 B — equals the table below |

Re-measure every row immediately before C1. If the image, pod or hashes differ,
stop and report; do not adapt the plan in flight.

1. `agent-scripts` holds **both** files at their expected hashes — the C4 state:

   | file | sha256 (16-char prefix) | bytes |
   |---|---|---|
   | `scout.js` | `1824967e200dab94` | 5852 |
   | `bindings.json` | `10cef1b830853225` | 26 |

   `bindings.json` carries `{"Scout": "scout.js"}` (pretty-printed, 3 lines —
   26 bytes, so a byte-exact restore matters). Read both with a hash, never by
   printing the script. Verify in-pod, on the **same pod** the arm will use:

   ```
   kubectl -n minecraft-test exec "$POD" -c agent -- \
     sha256sum /srv/aibot-scripts/bindings.json /srv/aibot-scripts/scout.js | cut -c1-16
   ```
2. Scout's inventory is stocked enough to make a store observable (the run-5
   method: two stacks, the non-selected one must be the one that moves).
3. The runner answers `ready:true` **and** a real tick — `ready` alone is not
   enough; it stayed true through the entire 05:57–10:15Z outage.

### 8.4.4 C2 — dead runner, closed port (EXECUTED 2026-11-13: PASS; kept as the record)

**Approved as option 2** (lead ruling 10:50Z, row `…1b24fe6e9c67c4c9`). The
reviewer's BLOCK on `ff3745a` assumed a whole-pod URL cut silences all five
bots. It does not: `_get_script_tick` returns `None` for a bot with no bound
script path **before any `ScriptTick` or transport exists**
(`agent.py:2808-2817`), so an unbound bot never reads `SCRIPT_RUNNER_URL`. Only
bound bots observe the cut. This section supersedes §8.3's `:894`/`:918` premise
that four bots would fall back — see the delta recorded there.

The cut is agent-side. Set `SCRIPT_RUNNER_URL` to a closed port **for the agent
Deployment only**, recreate the pod (§8.4.2 procedure, not `rollout restart`),
observe, then restore and recreate again.

1. **Prove Scout is the only bound bot, before and after the arm.** Read the
   live map from inside the pod (`exec … -c agent -- cat`) and count its keys;
   assert exactly one key, `Scout`. Then confirm the other four bots' tick
   lines are **unchanged across the arm** — a delta in their behaviour means the
   cut reached them and the arm is void.
2. Capture pre-state: `kubectl -n minecraft-test get deploy aibot-agent-test -o
   jsonpath='{.spec.template.spec.containers[0].env}'` → save to a file on
   controlplane, and **read it back**.
3. ⚠ **The Deployment is paused, so an env patch does not roll out** (lead
   requirement (c)). Publishing a template change on a paused Deployment updates
   `spec.template` but creates **no new ReplicaSet**; deleting the pod then
   recreates it from the *old* RS template and the arm silently runs the
   previous config — the §8.3.1a shape. Before the arm, **diff the paused
   template against the running RS template** and list any pending change a
   resume would apply:

   ```
   kubectl -n minecraft-test get deploy aibot-agent-test -o jsonpath='{.spec.template.spec.containers[0].env}' | sha256sum
   kubectl -n minecraft-test get rs -l app=aibot-agent,tier=test \
     -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.readyReplicas}{"\n"}{end}' | awk '$2==1'
   ```
   then hash the **name that prints** (exactly one RS has `readyReplicas=1`;
   eleven exist, the rest are scaled to 0):

   ```
   kubectl -n minecraft-test get rs "$RS" -o jsonpath='{.spec.template.spec.containers[0].env}' | sha256sum
   ```

   **Resolve the RS dynamically, never by name** (reviewer, 10:46Z). A literal
   such as `…-6b65bdfc95` is only correct until the first `rollout resume` in
   this same step, which creates a new RS; the next arm would then hit
   `NotFound`. Polarity there is safe — empty input hashes to `e3b0c442` and
   mismatches, so it stops rather than silently passing — but it halts the run.

   They were **identical** (`fe1a4d3c…`) when this was written, so resuming
   applies nothing pending. **If they differ, stop** and report the delta before
   resuming — resuming would then deploy a change this plan never measured.
   Then `kubectl -n minecraft-test patch deploy … --type=json` (the real patch,
   not a dry run), then `kubectl -n minecraft-test rollout resume
   deploy/aibot-agent-test`, recreate the pod, and **prove the
   new pod's env took effect**: `SCRIPT_RUNNER_URL` present with **host only,
   no credentials** (`127.0.0.1`), read from inside the new pod. Record
   set/unset and host; never print a secret.
4. Drive the goal via `inject_chat` (below). **Expected:** for every tick,
   `falling back to planner: runner fallback_connect_refused: connect refused: ...`
   — the state is `STATE_FALLBACK_REFUSED` (`script_client.py:115`, set at `:169`).
   Record the exact reason text as emitted, not as expected.
5. **Void if:** the **detail prefix** is not `connect refused:` — the state alone
   is not the discriminator (reviewer measured 10:42Z: `ConnectTimeout` also maps
   to `fallback_timeout`, so C2a and C2b can share a state); or the bot logs no
   `[Scout/script]` line (means the binding was lost, not that the runner was
   unreachable); or the new pod's `SCRIPT_RUNNER_URL` still points at the real
   runner (the paused-deployment trap in step 3).
6. **After the arm, restore and leave the Deployment paused** (its pre-run
   state). Record in the evidence whether it was resumed and re-paused, with the
   resume's diff from step 3.

### 8.4.5 C2b — accept and never reply (the bounded wait) (EXECUTED 2026-11-13 11:14–11:16Z: PASS; kept as the record)

**Revised 11:06Z: this arm reuses the running C2a pod** (lead ruling 11:03Z).
The URL C2a runs against — `http://127.0.0.1:9` — is a genuinely closed port in
that pod (measured: nothing listens there, one container, no sidecar), so C2b
is the *same* URL with something bound to it. No env patch, no restart, no new
ReplicaSet; the arm transition is a single `bind`. §8.4.5.1 is the procedure.

The distinguishing evidence is state `STATE_FALLBACK_TIMEOUT`
(`script_client.py:116`) **with** the listener's own `accepted` record
timestamped before it. Both `connect timeout:` (`:165`) and `read timeout:`
(`:167`) are acceptable prefixes — `requests` may report either against an
accepting silent socket, and the code at `:163-164` says the bot cannot tell
them apart. The two arms are why both cases are required: a refused connection
returns immediately and cannot exercise a missing timeout. §4.4's
accept-and-never-reply test covers the unit; this is the same branch on TEST.

**Void if** the bot hangs (no fallback line within the documented tick bound) —
a real defect, reported as one, not worked around — or if any `connect refused:`
line appears **after** the first accept, which means the listener died mid-arm.

**Inherits from §8.4.4** the only-bound-bot proof and the new pod's env proof
(the env is unchanged here, so the latter is a confirmation, not a patch). It
does **not** inherit the paused-Deployment diff or the detail-prefix void rule:
the Deployment stays resumed for the whole reuse, and the discriminator here is
the accept record and its timestamp (§8.4.5.1, evidence 2 and 4).

#### 8.4.5.1 The listener (ran for C2b on 2026-11-13; 48 accepts, 11:14:17–11:16:13Z)

§8.4.5 said "a listener that accepts and holds" without saying how to build one
or how to know it held. This subsection supplies the missing step. It adds no
new image, no new Service and no new port on the agent.

**Revised 11:06Z on the lead's ruling (11:03Z): C2b reuses the C2a pod.** C2a
is running now in `aibot-agent-test-6f76986444-vqs44` (started 11:01:22Z) with
`SCRIPT_RUNNER_URL=http://127.0.0.1:9`, bindings `10cef1b8`, `scout.js`
`1824967e`, Deployment **resumed**, serving RS `…-6f76986444`. Because the URL
is already the one C2b needs, there is **no env patch, no second restart and no
second ReplicaSet**, and the paused-Deployment steps (§8.4.4 step 3) do **not
apply to C2b**. The arm transition is a single `bind` inside the live container.

**Measured before writing this (read-only, 11:04Z, in that pod):**

| Question | Result | How |
|---|---|---|
| Can the container bind port 9 (<1024)? | **Yes** | `id -u` → `0`. No `USER` in `agent/Dockerfile`, no `runAsUser`, no `capabilities` in the pod spec, so the process is root and the unprivileged-port floor does not apply. Confirmed by an actual throwaway `bind(('127.0.0.1',9))` → `BIND-OK`, socket closed immediately |
| What serves `:9` today? | **Nothing** | One container in the pod (`agent`); no sidecar. A `connect` probe → `ConnectionRefusedError [Errno 111]`. The live log shows `fallback_connect_refused … Connection refused` |
| Is the Deployment resumed? | **Yes** | `.spec.paused` empty |

The middle row is the one that makes this arm cheap *and* is the one my first
draft guessed wrong: it said what serves `:9` was "not established" and
speculated about a sidecar or proxy. There is no sidecar and no proxy. **The
URL C2a runs against is a genuinely closed port**, which is exactly why the
same URL can become C2b's silent port the moment something binds it.

⚠ **The isolation is the env value, not the network.** The real runner is still
reachable from this pod: `AGENT_SCRIPT_RUNNER_SERVICE_HOST=10.107.105.168` is
injected and `agent-script-runner.minecraft-test.svc.cluster.local` resolves
(reviewer, 11:09Z). The agent uses neither, because `config.py:16` reads
`SCRIPT_RUNNER_URL` and every consumer is downstream of it — a grep of the image
finds six references, all in `config.py`/`script_tick.py`, and none reads the
injected variables. So the arms are isolated **because the client keys off one
env var**, and not because the runner is unreachable. Do not read the
`ConnectionRefused` above as evidence of isolation. If anyone later points
`SCRIPT_RUNNER_URL` at the service name, this isolation disappears and C2b's
listener would be a second, unused socket beside a working runner.

**What the listener must do, and why each part is load-bearing.**

| Requirement | Why it is not optional |
|---|---|
| Bind `127.0.0.1:9` **inside the agent pod's network namespace** | The agent reads `SCRIPT_RUNNER_URL` and connects on loopback (`script_client.py:161`); only a process in the same netns is reachable at `127.0.0.1`. Reusing the port means reusing the env, which is what makes the arm a single bind |
| **Accept the connection, then never write** | An un-accepted connection sitting in the listen backlog still completes the TCP handshake in the kernel, so `connect()` returns success and the client stalls the same way — but the listener has then proved nothing about *its* accept path. Accepting makes the arm unambiguously C2b |
| Hold the connection **> 300 ms** | `SCRIPT_TIMEOUT = 0.3` (`script_client.py:109`). Holding for less than the bound would let the client read a close as an error and never reach the timeout branch |
| **Prove the accept happened** | Same state, either prefix, for both arms (§8.4.5.1 evidence 2–3). The listener's own `accepted` record is the only thing that separates C2b from C2a; without it a run where nothing connected could still produce a `connect timeout:` and be misread as a pass |

**Image: the existing agent image, no new pull.**
`harbor.arcadia-ecs.local/aiplayermod/agent@sha256:a9e75ad1…` is currently
serving, its base is `python:3.11-slim` (`agent/Dockerfile:10`) with a working
`python3`, and it is already pulled on the node. The listener is a `python3 -c`
run in the **same container** as the agent — a second container would share the
netns and also work, but it changes the pod template, and any template change
forces a recreation, which is the cost this revision exists to avoid.
**Do not add a container.** Resources stay as they are: the pod's existing
`cpu=1 / memory=512Mi` limits are untouched, and the listener idles at a
negligible cost.

**The listener**, verbatim, to be placed in the pod with `kubectl exec` as a
backgrounded process. It writes one line per accepted connection to a file in
the pod, so the proof survives the process:

```
kubectl -n minecraft-test exec "$POD" -c agent -- sh -c '
  nohup python3 -u -c "
import os, socket, sys, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((\"127.0.0.1\", 9)); s.listen(8)
sys.stderr.write(\"pid %d\n\" % os.getpid()); sys.stderr.write(\"listening\n\"); sys.stderr.flush()
held = []
while True:
    c, _ = s.accept()
    sys.stderr.write(\"accepted %d\n\" % int(time.time())); sys.stderr.flush()
    held.append(c)          # keep it OPEN and never reply; the loop keeps accepting
" >/tmp/c2b.log 2>&1 &
' ; sleep 1 ; kubectl -n minecraft-test exec "$POD" -c agent -- cat /tmp/c2b.log
```

The second command must print `listening`. If it does not, the listener is not
up and the arm has not started. If it prints `Address already in use`, something
else took `:9` between the measurement above and this step — stop and re-probe
rather than proceeding, because the arm would then be measuring another
process.

The listener starts with `pid <n>` because **`pgrep`, `pkill`, `ps` and
`procps` are all absent from this image** (reviewer-measured 11:09Z: `sh: 1:
pgrep: not found`, inner rc 2). The pid has to come from the listener itself.

**Why the loop does not sleep inside the accept.** An earlier draft called
`c.settimeout(60); time.sleep(60)` inside the loop, which holds one connection
for a full minute and accepts nothing else meanwhile. The reviewer reproduced
the consequence: five clients one second apart produced exactly **one**
`accepted` line, and a client arriving while the listener was sleeping still saw
`read timeout` after 300 ms — **identical to C2b evidence, with nothing
accepted for it**. That is the failure this section's own table warns about, and
it would make an accept count meaningless. Appending to `held` keeps the socket
open (so the client still stalls) while leaving the loop free to accept every
connection. The thread never writes, never closes, and never replies.

**Bound the held list.** `held` grows one socket per tick and nothing reaps it,
so over a long arm it is an unbounded resource against the pod's existing
`memory=512Mi` limit. One client is enough to prove the arm; cap it at 32 and
close the surplus after accepting it, which still exercises the accept path and
the stall without letting the list run away:

```
    held.append(c)
    if len(held) > 32:
        held.pop(0).close()
```

**The cap is safe at both layers, measured twice.** On bare sockets (this VM,
11:12Z): six clients against a cap of two each stalled the full 300 ms and none
saw an early EOF — the client never writes, so the peer's FIN is not observed
before the read deadline. That measurement was raw-socket only, so the reviewer
closed the gap with the **real `requests` client**: eight posts through a cap of
two all raised `ReadTimeout` and **none** raised `ConnectionError`, i.e. a
capped close cannot manufacture a `connect refused:` and void the arm. The
reviewer also found the cap closes sockets *immediately* (accepted and closed in
the same second) and every client still ran the full 0.303 s, because `requests`
is blocked in `recv` and never observes the FIN before its own deadline.
`SCRIPT_TIMEOUT = 0.3` against a ~2.3 s tick means the cap cannot strand an
in-flight request either: the request holding the oldest socket gave up long
before the cap could reach it (§8.4.8 for the rate). So the cap is a defensive
bound with no measured cost, **not** a working mode — and keep it: an unbounded
list grows one socket per tick against a 512Mi limit.

⚠ **The evidence window starts at the first `accepted` line, not at
`listening`.** This is the lead's requirement (2) and it is the subtlest trap in
the arm. Ticks that fall between the bind and the first connection are
**still C2a-shaped**: for that interval the listener is bound but the agent's
next tick may already have failed to connect, or the listener may be up and not
yet connected to. Either way a `fallback_connect_refused` line in that gap
belongs to the closed-port arm and must not be counted as C2b evidence. The
window is:

| Boundary | Marker |
|---|---|
| **opens** | the first `accepted <epoch>` in `/tmp/c2b.log` |
| **closes** | the kill, before the restore (§8.4.5.1 deletion) |
| **granularity** | one second: the accept epoch truncates, so a line inside the first accept second is ambiguous and not counted |

Every tick line used as C2b evidence must have a timestamp **strictly after**
that first accept epoch. A `read timeout:`/`connect timeout:` line before it is
not C2b evidence even though it looks identical; a `connect refused:` line after
it means the listener died mid-arm and the arm is void.

⚠ **The accept epoch is second-resolution, so "strictly after" is one-second
granularity, not sub-second.** `int(time.time())` truncates, and accepted epochs
repeat within a run (several ticks land in the same second). A log line stamped
inside the *same second* as the first accept is therefore **ambiguous**: it could
have been emitted microseconds before or after the accept that opened the window,
and the two records have no common clock finer than the second. Treat it as
follows — a tick line in the first accept second is **not** counted as C2b
evidence (it is neither confirmed in nor confirmed out); evidence starts with the
first line strictly later than that second. Use a few seconds of margin after the
first accept as the clean window. `--timestamps` gives RFC3339 with sub-second
precision, but the *accept* side does not, so the comparison is only as fine as
the coarser of the two records.

**Delete it before restoring the env.** With the reuse route the env does not
change, so the restore is §8.4.9 run **once** at the end (env back, re-pause,
read both back) — but the listener still has to go first, because it is a
process in the pod and not a Deployment object:

```
# the pid comes from the listener's OWN start line (evidence 0), not from a
# process scan -- pgrep/pkill/ps are absent from this image, and a /proc or
# source-text scan would also match the cleanup probe below
PID=$(kubectl -n minecraft-test exec "$POD" -c agent -- \
        sed -n 's/^pid \([0-9][0-9]*\)$/\1/p' /tmp/c2b.log)
kill_rc=0
kubectl -n minecraft-test exec "$POD" -c agent -- kill "$PID" || kill_rc=$?
probe_rc=0
kubectl -n minecraft-test exec "$POD" -c agent -- \
  python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",9))' || probe_rc=$?
echo "PID=$PID kill_rc=$kill_rc probe_rc=$probe_rc"
```

`probe_rc=0` means the port is free and the listener is gone; a non-zero
`probe_rc` means it is still holding the port — do **not** start the restore
until it is gone. `kill_rc` is reported **separately and deliberately**: an
earlier draft wrote the kill and the probe into one compound command and then
read `$?`, which is the *probe's* status, not the kill's. The reviewer measured
`kill_rc=2` against `FINAL rc=0` — the documented rc could not see the kill
failing at all, and the step looked healthy precisely because a live listener
keeps the port held. Capture both, print both, judge both.
Because the env is unchanged in the reuse route, a survivor here is worse than
in the restart route: the restored pod would keep pointing at `:9`, now served
by the fake listener, and §8.4.9's re-read would confirm a URL that no longer
reaches the real runner. Deleting the pod is the guaranteed fallback (§8.4.2).

*(A `pkill -f` on the listener's own source text is wrong here: the cleanup
probe is also a `python3 -c`, so a pattern broad enough to find the listener
also matches the probe and the check kills itself before it can answer.)*

**Evidence to capture, in order.**

0. `pid <n>` from `/tmp/c2b.log` — needed for the deletion step below; it is
   the listener's own pid, since no process-listing tool exists in this image.
1. `listening` from `/tmp/c2b.log` — the listener is up. **This is not the
   start of the evidence window.**
2. The first `accepted <epoch>` — **this is the start of the evidence window.**
   Record its epoch.
3. The agent's fallback line with state `STATE_FALLBACK_TIMEOUT`
   (`script_client.py:116`), **timestamped after the epoch in 2**. Record the
   exact detail prefix as emitted, and record the line's own timestamp so the
   ordering is checkable and not asserted.

   ⚠ **The agent's log lines carry no timestamp of their own** (reviewer,
   11:09Z). "Record the line's timestamp" has nothing to read unless the log is
   fetched with `--timestamps`, which prefixes each line with RFC3339 and was
   confirmed to agree with the pod clock and the listener epoch within 3 s.
   **Every `kubectl logs` used for C2b evidence must carry `--timestamps`:**

   ```
   kubectl -n minecraft-test logs "$POD" -c agent --timestamps --since-time="$SINCE" \
     | grep -F 'STATE_FALLBACK_TIMEOUT'
   ```

   Compare that RFC3339 stamp against the accept epoch from evidence 2, **at
   one-second granularity** (the accept epoch truncates to whole seconds; see
   the ambiguity rule above). A line inside the first accept second is not
   counted. Without `--timestamps` the ordering is asserted, not checkable —
   and asserted ordering is how an arm that saw nothing gets counted as a pass.
   Both `connect timeout:` (`:165`) and `read timeout:` (`:167`) are valid C2b
   evidence, and the code says so at `:163-164`: *"Accepted-then-silent, or
   refused after the connect phase. Both are treated as a stall: the bot cannot
   tell them apart and must not wait."* **Which of the two `requests` will
   report here is an expectation, not a measurement** — the unit test at
   `agent/test_script_client.py:166` asserts only `STATE_FALLBACK_TIMEOUT`,
   never the exception class or prefix. Treat either as valid and decide the
   arm on evidence 2 and 4. *(An earlier draft of this step called
   `connect timeout:` C2a's branch and a void; that was wrong, and the code
   comment above is what refutes it.)*
4. Any `connect refused:` line **strictly later than the first accept second**
   → the listener died mid-arm; the arm is **void**, not passed. A `connect
   refused:` inside the first accept second is ambiguous, not void — it belongs
   to the C2a gap and is neither evidence nor a failure.
5. The deletion proof above (`rc=0`), captured before the restore.

**The void rule for this arm is therefore the accept record and its timestamp,
not the state and not the prefix.** C2a and C2b share a state constant *and* a
possible prefix; the only thing that separates them is whether a connection was
accepted, *and when*. §8.4.4 step 5's detail-prefix rule does not transfer
here. Stated plainly because the two arms share so much that an earlier version
of this text assumed they also shared a discriminator.

**What this arm still cannot prove.** The unit test
(`agent/test_script_client.py:95`, `_NeverReplies`) covers the client's branch
with a real accepted-and-silent socket. This TEST run adds the live deployment
path — the real `requests` stack, the real env, the real pod — and nothing
more. It is not independent evidence for the timeout *value*; that stays the
unit test's claim (`test_script_client.py:150`).

### 8.4.6 C1 — control arm, bindings absent

**Two branches, two different evidences — pick one and state its own.** Verified
at `agent.py:2767-2781` (reviewer measured both, 10:42Z):

| state | code path | log evidence |
|---|---|---|
| `bindings.json` **absent** | `FileNotFoundError` → `:2767-2771` | **a line**: `no bindings at …; this bot runs the planner` |
| file present, **no Scout key** | `bindings.get` falsy → `:2779-2781` | **no line at all** (silent `return None`) |

This arm uses **absent-file**, so its evidence is a *present* line plus zero
dispatches. The earlier draft of this section configured absent-file and then
looked for the silent branch's evidence (no line at all); that was a
contradiction and it would have passed on either branch.

1. Save the current `bindings.json` (`{"Scout": "scout.js"}`, 26 bytes, sha
   `10cef1b8…`) to a file on controlplane; read it back.
2. Apply a ConfigMap with `bindings.json` **absent** (not an empty object —
   absent, so the `FileNotFoundError` branch is exercised).
3. Recreate the pod by the §8.4.2 procedure.
4. Drive the same goal. **Expected, all three:**
   - `[Scout/script] no bindings at /srv/aibot-scripts/bindings.json; this bot
     runs the planner` — present, once per load, quoting the text as emitted.
   - **zero** `[Scout/script] dispatch:` lines.
   - Scout still acts, via the planner. That is the baseline, not a failure.
5. **Void if** any `[Scout/script] dispatch:` line appears (not the arm), **or**
   the `no bindings at` line is missing (means the mount still has the old file
   or the pod did not recreate — §8.4.2's fingerprint check should already have
   caught that).
6. ⚠ **Do not gate on the bare `Scout/script` tag.** §8.3.4 at `:1287-1290`
   records this resolver line being counted as 1 instead of 0, because it *is* a
   `[Scout/script]` line. Count `dispatch:` lines and assert the `no bindings`
   line separately.

### 8.4.7 C4 — script arm (already evidenced by run 5; re-run only if C1–C2 void)

Restore `bindings.json`, recreate the pod (§8.4.2 procedure), drive the same
goal, confirm `dispatch: STORE_ALL seq=1` **and** the mod's accepted POST with a
destination read-back (the run-5 method at `01655d8`). This is the arm run 5
already supplied; it is listed so the four arms are compared under one method.

### 8.4.8 Acceptance, and what each arm is allowed to prove

- The proof is the **contrast**, not any single arm: C1 produces no script line,
  C4 produces a dispatch, under the same goal and the same method.
- Each arm must show its distinguishing line (§8.4.1). A missing line voids the
  arm rather than counting as a negative.
- The negative control is satisfied only when the log shows the full
  **script → fallback (with reason) → script** transition, which requires C2 or
  C2b followed by C4 with no pod recreation in between that changes other
  variables. "Recreation" here means the §8.4.2 procedure, and its own proof of
  a new pod + mount fingerprint is required before the C4 evidence is read.
- ⚠ **Known limit:** the fallback reason for a *trap* (`wasm_trap`, the 05:57Z
  regression) was in the past misreported as `script_error`; the runner fix
  `aa7b00a` corrects the classification but is **not deployed**. Until it is,
  C2's reason text on a trap-shaped failure is unreliable. The controls do not
  depend on trap classification (they cut the connection, not the sandbox), but
  a run that *also* observes a trap must treat the reason as suspect.

**Acceptance 4/5 of §8.3 are a NO-REGRESSION check, not proof of the fix**
(lead, 10:41Z). Measured before writing this: the pod running the **old** image
`a9e75ad1` (pod `…-cbpz9`, started 10:38:02Z, 0 restarts) was ticking healthily,
because the 10:15Z `/v1/destroy` already cleared the wedge.

Quote it as a **rate over a window bounded by the pod's own age**, never a raw
line count (reviewer, 10:46Z: an earlier "134 lines in 20 minutes" could not
reproduce — that pod is only ~8 minutes old, and the count drifts as the window
moves). Measured 10:46Z over `…-cbpz9`'s whole life, `--timestamps`, first to
last `dispatch:` line:

```
worked example, 10:46Z:
  214 dispatch lines / 497.4 s  ->  25.8 dispatch/min
  (rate = lines / window_seconds * 60; the interval is window/(lines-1) = 2.335 s,
   per-gap, not window/lines = 2.324 s. Do not quote the gap without saying which.)
```

**This is a worked example, not a checkable constant — re-measure it.** The pod
keeps ticking, so the same instruction gives a different count minutes later:
214/497.4 at 10:46Z, 244/564.9 three minutes on. *The rate is the stable
quantity* — 25.8, 25.9 and 25.8/min across three independent measurements — and
it is what to compare. A reader who re-runs the command and cannot reproduce the
raw count has not found a fault; re-derive the window and compare the rate.

**`dispatch:` is the line counted, one per tick.** Each tick also emits
`N action(s) this tick`, so the bare `[Scout/script]` tag appears in pairs;
counting the tag doubles the figure (428 vs 214, pair ratio exactly 2.0). Say
which line you counted, and take `first→last dispatch` as the window rather than
a wall-clock span that can exceed the pod's age. "Scout's ticks stop erroring" therefore passes on the
old image too and cannot attribute anything to `aa7b00a`. **The fix is proven by
the reviewed suite** (127/127 with the boundary-capture mutation at 126/127),
not by this rollout; the rollout's job is to show it does not regress.

Two checks the lead requires alongside acceptance 4/5, because §8.4 recreates the
pod four times and the runner is shared:

1. **cardgame's sessions survive the recreation** or are re-established after it
   — the runner is shared and `replicas=1` on the agent, so a deleted pod briefly
   takes every minecraft bot's script tick with it.
2. **Restart count and child respawns stay flat for 10 minutes after the final
   recreation.** ⚠ The fix inverts recycling to *default-on*: any error without
   script provenance now recycles a worker. A count that climbs here means the new
   default is too eager and the rollout should be rolled back on the §8.4.9
   command, not nursed.

### 8.4.9 Rollback

Restore the saved `env` patch and the saved `bindings.json`, then recreate the
pod by the §8.4.2 procedure, and re-read both back from the **new** pod. The
shared runner is untouched at every step, so it has no rollback.
Verified-by-re-read, not by `apply` returning 0. Confirm the pod name changed
and its `.status.startTime` is later than the restore; a re-read from the old
pod proves nothing about the restore.

*(Updated 2026-11-17: the Deployment is now unpaused, and C1 changes only the
ConfigMap, so for C1 the rollback is the ConfigMap restore plus a pod
recreation, and the check is that `spec.paused` and the template annotations are
unchanged from the §8.4.3 baseline. The paragraph below applied to the C2 arms
on 2026-11-13.)*

**Restore the pause state too.** The Deployment's pre-run state is
`spec.paused=true`; if an arm resumed it, `kubectl -n minecraft-test rollout
pause deploy/aibot-agent-test` at the end and re-read `spec.paused` — a rollback
that leaves the Deployment resumed has left a pending template change free to
apply on the next pod recreation, which is precisely the trap §8.4.4 step 3
exists to prevent. Also confirm the restored env's sha256 matches the pre-state
file captured in step 2, and that `SCRIPT_RUNNER_URL` again points at the real
runner (host and port read from inside the new pod; no credentials printed).

### 8.4.10 Driving the goal

`inject_chat` from inside the agent container, per §8.3.4 — never rcon, never
`/api/directive`. The key is read from the in-pod `api` module and never printed
or placed on a command line:

```
kubectl exec -n minecraft-test deploy/aibot-agent-test -c agent -- \
  python3 -c 'import api; print(api.inject_chat("Scout","OperatorTest","Scout, please store all your items in the nearby chest."))'
```

Include the bot's name in the text — that is what routes it.
