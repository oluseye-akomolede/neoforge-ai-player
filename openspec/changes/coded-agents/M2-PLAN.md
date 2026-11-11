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

Built in the agent, from data it already fetches, into contract §3's shape:

```json
{ "bot": {"name","health","food","position":{"x","y","z","dim"}},
  "inventory": [...],
  "nearby": {"blocks":[...], "mobs":[...]},
  "task": {"directive","progress",...} }
```

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
| `do` | `api.set_directive(bot, directive, ...)` (`agent/api.py:428`) — the existing dispatch |
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
trajectory JSONL, the store holds exactly one `STORE_ALL` record (coordless,
archive dated 2026-07-16, four months stale), and one stale record is not
current behaviour. The pinning rests on the structural argument above
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
  scout.json: |
    {"revision": "sha256:<hash>", "game": "minecraft", "bot": "Scout"}
```

```yaml
# minecraft-test/aibot-agent-test   (added to the existing pod spec)
volumes:
  - name: agent-scripts
    configMap:
      name: agent-scripts
# ...and on the existing `agent` container:
volumeMounts:
  - name: agent-scripts
    mountPath: /opt/aibot-agent/scripts
    readOnly: true
```

Scout's script path in config becomes `/opt/aibot-agent/scripts/scout.js`. Edits
are a `kubectl apply` of the ConfigMap plus a pod restart — no image build, which
is the whole reason decision 3 chose this over baking them in. `readOnly: true`
because nothing in the agent should write its own instructions.

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
| `minecraft-test/aibot-agent-test` | **edit** — second volume + readOnly mount at `/opt/aibot-agent/scripts` (see §6 on why not `deploy/`) |
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

- `agent/profiles/scout.json` gains `"runner_url"` and `"script_path"`
  (`/opt/aibot-agent/scripts/scout.js`), consumed alongside the existing
  profile keys.
- **No other profile is touched.** `agent/profiles/*.json` contains no
  `url`/`runner`/`endpoint` field today (verified: the grep returns nothing), so
  this adds one field to one file rather than altering a shared default.
- Absent field means fall through to the existing behaviour, so a profile
  without `runner_url` behaves exactly as it does now.

The isolation is therefore **one file, not shared state** — which is what makes
it clean. It is also why the plan must name it: an implementer reading
"agent-side, on Scout alone" against a single-replica Deployment with
process-wide env will reach for the env var, and the result would be a proof that
passes while secretly cutting off every bot.

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

Evidence is the same shape as the positive case, and must show all three
transitions in the agent log: **script → fallback (with reason) → script**. A
control that shows only "it fell back" does not show it recovered.

---

## 8.3 The TEST run plan (step 4, Part B)

**Status: proposed, not executed.** Nothing below has run. Every cluster fact in
it was read at 12:4xZ from `minecraft-test` and is true of that moment only.

### 8.3.1 What is true of the cluster before this plan

| Fact | Value | How read |
|---|---|---|
| Image | `harbor.arcadia-ecs.local/aiplayermod/agent@sha256:…` (**pin by digest before rollout**) | `kubectl get deploy -o jsonpath` |
| Pods | 1/1 `aibot-agent-test` | `kubectl get pods` |
| ConfigMap `agent-scripts` | **absent** | `get cm` → NotFound |
| Deployment volumes | `agent-data` PVC only — no script mount | manifest + live |
| Deployment env | `NN_COMPRESSOR_URL` only; **no `SCRIPT_RUNNER_URL`** | live env |
| Runner service | `agent-script-runner:8080` reachable in-namespace | `get svc` |
| Scout profile | image file `profiles/scout.json`, **no `script` key** | `exec cat` |

Scout must therefore be given the script **and** the runner URL, or the script
path is dead on arrival: `_get_script_tick` returns None without `script`, and
the transport falls through without `SCRIPT_RUNNER_URL`.

### 8.3.2 The change, in three parts

1. **ConfigMap** — apply `deploy/agent-scripts.yaml` (already generated from
   `agent/scripts/scout.js`; the drift test keeps the two equal).
2. **Mount + env** — add to the container:
   - `volumeMounts: [{name: scripts, mountPath: /opt/aibot-agent/scripts, readOnly: true}]`
   - `volumes: [{name: scripts, configMap: {name: agent-scripts}}]`
   - `env: [{name: SCRIPT_RUNNER_URL, value: "http://agent-script-runner.minecraft-test.svc.cluster.local:8080"}]`
3. **Scout's profile only** — add `"script": "/opt/aibot-agent/scripts/scout.js"`.
   Profiles live in the image at `profiles/<Bot>.json`; this bot's copy is on
   the `agent-data` PVC, so this is a **pod-local file edit**, not a ConfigMap or
   a code change. It is the one step that is *not* reproducible from git, which
   is why it is spelled out here rather than assumed.

### 8.3.3 Order, and why

1. Apply the ConfigMap. Nothing consumes it yet — safe on its own.
2. Patch the Deployment (mount + env). The new pod has the script available but
   no profile names it, so script mode is still off: **the restart changes no
   behaviour**. This is the deliberate point of the order — the restart's risk is
   paid at a moment when the feature is provably inert.
3. Confirm 1/1 and that the pod has the file (`cat /opt/aibot-agent/scripts/scout.js`).
4. Edit Scout's profile in the pod and let the agent pick it up on its next
   construction of that bot, or restart the pod once more (state which was done).
5. **Control first, then the real run** (§8.3.4).

### 8.3.4 The negative control

The proof is worthless without one: a bot that happens to store something while
the script is loaded proves nothing. Both halves are required, in this order.

- **Run 1 (control):** Scout's profile *without* `"script"`. Drive the same goal
  and record whether any `STORE_ALL` POST reaches the mod. Expected: none from
  the script path (the planner may still emit one — that is the baseline to
  compare against, not a failure).
- **Run 2 (script):** same goal, `"script"` added. Record the runner's action,
  the agent's applied `seq`, and the mod's POST response.

The control must **never stop the runner** (lead, 11:37Z) and must cut Scout off
agent-side only — the shared runner serves other work.

### 8.3.5 Verification, per piece

| # | Evidence | Failure looks like |
|---|---|---|
| 1 | Runner log: tick with `bot_id: "Scout"`, script `revision`, non-empty `actions` | no runner line at all → the tick never left the agent |
| 2 | Agent log: applied `seq` matching the runner's | same `seq` never applied → binding dropped it |
| 3 | Mod POST response: `status: accepted`, `STORE_ALL`, **coordless** | coordinates present → §3's pin is wrong, record it |
| 4 | Run 1 produces no script-path POST | a POST with no script → something else is emitting it |

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
- **Profiles are pod-local**, not in git: the step-3 edit is not recoverable from
  a checkout. Record the exact file edited and its before/after `script` key.

### 8.3.7 What this plan does NOT claim

- It does not claim the planner emits coordless `STORE_ALL` in the wild. Two
  producers are known to (`agent.py:1888` bare, `SkillRegistry.java:154` bare);
  a raw model emission is untraced. Run 1 records the planner's real form.
- It does not claim the bot will store anything. The script may return early
  (low health, task in flight) — that is a fall-through to the planner, which is
  correct behaviour and would make run 2 look like run 1. If both runs match,
  check the runner log for the tick before concluding the feature failed.

---

## 9. Rollback

No data migration and no schema change, so rollback is code-only:

```
git revert <this change's commits>                              # agent-side only
kubectl -n minecraft-test rollout undo deploy/aibot-agent-test
kubectl -n minecraft-test delete configmap agent-scripts
```

The last line matters: `rollout undo` reverts the Deployment to its previous
pod spec, which no longer references the ConfigMap, but **does not delete the
ConfigMap itself**. Left behind it is inert, but it is a stale script a later
reader might mistake for live. Delete it so the rollback leaves no artefact
claiming to be active.

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
   for every re-proof, where a ConfigMap needs an apply and a pod restart. The
   original rationale here said the control requires "stopping and restarting
   the runner mid-proof" — that is no longer true, since the lead ruled
   (11:37Z) that the control must never stop the shared runner and cuts Scout
   off agent-side instead. The decision stands on the rebuild cost alone. If a
   later change does bake scripts in, the rebuild cost must be stated, not left
   implicit.
