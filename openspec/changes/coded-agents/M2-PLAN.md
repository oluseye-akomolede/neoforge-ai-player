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
| **snapshot bound** | 100 ms | this plan's proposed cap on the read side of a script call (§4.4). |

An earlier draft compared a 150 ms snapshot against "the tick budget (250 ms)".
That is two errors in one sentence: 250 ms is `deadline_ms`, not the tick
cadence, and the cadence is 2 s, not 250 ms.

**Discovery risk — measure before assuming.** These four calls are four HTTP
round trips to the mod. The plan's first implementation step is to *measure*
their combined latency on TEST. A tick runs every **2 s**, so a snapshot costing
150 ms leaves ~1850 ms — the cadence is not close to being the binding
constraint. The number that matters is the 100 ms bound in §4.4, and the
measurement is what tells us whether four round trips fit inside it. If they do
not, the fix is a single aggregated `GET /bot/{name}/snapshot` in the mod rather
than four calls. **I am not adding that endpoint unless the measurement says it
is needed** — it is the larger change and may be unnecessary.

---

## 2. Task 3.2 — action binding limited to the existing dispatch set

The script can request exactly three calls (contract §4.1): `api.do(directive,
args)`, `api.say(text)`, `api.send(otherBot,msg)`. The runner returns
`actions[]`; the agent maps each to the path the planner already uses:

| action | agent path |
|---|---|
| `do` | `api.set_directive(bot, directive, ...)` (`agent/api.py:428`) — the existing dispatch |
| `say` | the existing chat-send path |
| `send` | the existing inter-bot message path |

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
`SCRIPT_DIRECTIVE_KINDS` into a generated Python module that is committed. A test
regenerates from the Java source and asserts the committed module matches, so
adding an enum member without regenerating fails the suite rather than silently
narrowing what scripts may call. The generator parses the enum's member list, not
the file's prose.

### SKILL is accepted by the set but not satisfiable as a bare directive

Admitting all 37 includes `SKILL`, whose validity depends on its **payload**, not
its name — `agent/agent.py:3849` dispatches it as `set_directive(b, "SKILL",
target=sid, extra=...)` with a skill id. And `SkillValidator.java:59` rejects
`SKILL` as a directive leaf outright ("a directive leaf must not be SKILL — use a
skill-ref node"), which is precisely why it is absent from the frozenset.

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

- **The kinds are UPPERCASE** (`MINE`, `GOTO`, `SEND_ITEM`). The dispatch
  upper-cases at `agent/agent.py:904` before comparing, so a script naming
  `"mine"` must be normalised or refused — silently passing lowercase through
  would reach the mod and fail there, where the error is far away from the cause.
- **`api.set_directive` does NO validation** (`agent/api.py:428`). It builds
  `{"type": name}` and POSTs. So the rejection described below **does not exist
  yet** — this plan introduces it, in `script_client.py`, on the agent side.

The runner deliberately does not validate names (contract §4.1 — the set is the
game's). The agent therefore resolves the name at the moment it applies the
action, and an unknown or wrong-case directive is **rejected and logged**, never
passed through.

**Proof required:** a test that submits a script calling `api.do("NOT_A_REAL_-
DIRECTIVE")`, and asserts (a) the runner returns it as an action (it does not
validate), and (b) the agent refuses to dispatch it and logs the refusal. That
pair is the whole point of 3.2: the boundary is enforced on the side that owns
the set.

---

## 3. Task 3.3 — parity proof for one action

Pick **one** directive with an unambiguous, observable effect: `say`. It is the
best parity subject because the evidence is a line in the game log — no physics,
no pathing, no timing.

Method: two runs of the same bot in the same place.

1. Planner path: the bot reaches the `say` directive through the existing agent
   code. Record the chat line and the sequence of API calls.
2. Script path: the same `say` arrives via `api.say` from the runner. Record the
   same two things.
3. Assert the **API call sequence is identical** and the chat line is identical.

Why `say` and not `MINE`: a movement action's parity is confounded by tick timing
and world state; `say` isolates *does the script→action binding produce the same
effect as the planner→action binding*, which is the actual claim. `MINE` parity
is worth doing, but as a separate, later check — not as the first proof.

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
**100 ms**. This is not the runner's `deadline_ms` (250 ms) and not the 2 s tick
cadence — see the table in §1. The agent's bound is the *client-side* one, and it
must be shorter than what the runner can take, so the agent gives up first and
falls back rather than waiting on a runner that is already past its own budget.

**The 100 ms must be passed explicitly, not inherited.** `agent/api.py:33`
defines `_post(path, data=None, timeout=5)` — a **5 s** default, sized for
planner calls that may do real work. Reusing `_post` without an explicit
`timeout=0.1` would let one slow runner stall a 2 s tick five times over, and it
would do so silently because 5 s is a legal value. The script path therefore
calls `_post(..., timeout=SCRIPT_TIMEOUT)` where `SCRIPT_TIMEOUT = 0.1`, and
§7 requires a test that pins it: a unit test asserting the script path passes
0.1, which fails if someone drops the argument and falls back to the default.

States and behaviour:

| runner state | detection | bot action |
|---|---|---|
| connect refused | immediate (§4.3) | fall back to planner this tick |
| accepted but silent | read timeout at 100 ms (§4.4) | fall back to planner, log |
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

**Hand-written**, for `Scout`, stored as a file in the agent's config:

```
agent/scripts/scout.js          # the script source
agent/scripts/scout.json        # {"revision": "sha256:…", "game": "minecraft", "bot": "Scout"}
```

`revision` is the content hash, computed at load, so the runner's cache key and
the stored file cannot drift. Changing the script changes the hash, which the
runner treats as a new revision (contract §2 `script_revision` is required).

**How 6.x will read them later, without building 6.x now:** the scripts are
already plain files with a stable name→path convention and a content hash. The
player-visible read-only view becomes "list `agent/scripts/*.js`, show the source
and the revision" — a read over the same files, needing no new storage. That is
the design property worth having: **the storage choice for M2 is also the read
path for 6.x**, so building 6.x later needs no migration. Not to be built here.

Script content for M2 (deliberately boring — its job is to prove the path, not
to be a good bot): read the snapshot, `say` once when a condition holds,
otherwise return without acting, so the fallback and the script path are both
observable.

---

## 7. Files touched

| file | change |
|---|---|
| `agent/script_client.py` | **new** — `/v1/tick` client, bounded wait, snapshot builder |
| `agent/agent.py` | `BotRunner._loop`: try script, apply `actions[]`, fall back |
| `agent/config.py` | runner URL, token env, script path |
| `agent/scripts/scout.js`, `.json` | **new** — the first script |
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
3. **Game-side:** the observable effect of that action (the `say` line in the
   server log), matching §3's parity result.

The three together rule out every false pass: runner-only fails to show the bot
acted; game-only fails to show the *script* caused it; agent-only fails to show
either end. **A negative control is part of the proof:** stop the runner, confirm
the bot falls back to the planner and logs it with a reason, then restart and
confirm it returns to the script. Without that control, "it works" is untested
against the failure it is meant to survive.

---

## 9. Rollback

No data migration and no schema change, so rollback is code-only:

```
git revert <this change's commits>       # agent-side only
kubectl -n minecraft-test rollout undo deploy/aibot-agent
```

The runner is **not** removed — it is deployed, verified and independent; the bot
simply stops calling it and uses the planner. That is a property worth stating:
the M2 change is additive and its failure mode degrades to the previous
behaviour, not to no behaviour.

---

## 10. Order of work

1. Tick 4.1/4.2/8.1 in `tasks.md` — **done**, commit `5f52a79`.
2. Measure §1's snapshot latency on TEST (decides four-call vs new endpoint).
3. `script_client.py` + 4.3/4.4 tests (the bound and the fallback first, so the
   bot is never dependent on an unproven call).
4. Snapshot builder (3.1), then action binding (3.2) + its refusal test.
5. Parity (3.3) with `say`.
6. The first script + 8.2 proof, including the negative control.

Each step's tests run before the next. Gradle/agent tests: `-Xmx2g`
`--max-workers=2` `nice -n 19`.

---

## 11. Open questions for the reviewer

1. **§1's four-call snapshot**: agree that measuring before adding a mod
   endpoint is right, or is the aggregated endpoint obviously correct?
2. **§3.3 parity on `say`**: accept `say` as the parity action, with `MINE`
   deferred?
3. **§6 script storage in the agent image**: scripts ship in the agent image, so
   changing a script needs a rebuild. Acceptable for M2 (one hand-written
   script), but it is the thing that will hurt when 7.1 lands. Worth a ConfigMap
   now, or defer?

---

## Decided at review (2026-11-11 10:33Z)

The reviewer ruled on all three open questions. Recorded here so the plan does
not carry open items into implementation:

1. **§1 snapshot: measure first, and add no mod endpoint in M2.** All four calls
   are already made by the planner, so a short-TTL cache in `api.py` is
   agent-only work. Escalate to a mod endpoint only if the cache proves
   insufficient — and then as its own change, not folded into M2.
2. **§3.3 parity: `say` accepted**, with the silence counter-case above.
3. **§6 script storage: ConfigMap now, not deferred.** Deferring is the
   expensive choice, because §8's negative control requires stopping and
   restarting the runner mid-proof; a baked-in script would need a **rebuild**
   for every re-proof. If a later change does bake scripts in, the rebuild cost
   must be stated, not left implicit.
