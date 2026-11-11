# Review — M2 step 4, third gate (`9222435`)

**Row:** `qitem-20261111124635-9baa2a708ca95045`
**Verdict: PASS on the tree — the two blockers I filed are fixed and each fix
reddens under its own mutant. HOLD on a third defect the fix exposed: the script
path bypasses the agent-side handlers, so 6 of the 10 agent-side kinds it
accepts do something other than what they name.**

Read at `9222435` in this worktree, suites run here, then reset to `c311d44`.

---

## 1. B1, the profile path — verified, and the positive control is mine

The diagnosis matches mine and they went further than I could: `ls` on the pod
shows `/opt/aibot-agent/profiles/` with five profiles and
`/opt/aibot-agent/data/profiles/` **absent**. That is the fact I could not
establish from this seat, and it confirms the no-op.

The fix is the right shape. `load_profiles()` reads
`os.getenv("PROFILES_DIR") or os.path.join(os.path.dirname(__file__), "profiles")`,
so unset is today's path exactly. I ran it three ways, with `__file__` defined:

```
unset  -> ['Axiom', 'Forge', 'Mystic', 'Scout', 'Tiller']
set    -> ['X']                       (a tempdir holding one scout.json)
empty  -> ['Axiom', 'Forge', 'Mystic', 'Scout', 'Tiller']
```

Empty-string falls through because `or` treats it as falsy, which is the
behaviour you want and not one the code comments on.

**But there is no test for it, and that is the one guard this change lacks.**
Mutant B — restore `profiles_dir = os.path.join(os.path.dirname(__file__), "profiles")`
and ignore `PROFILES_DIR` entirely — **108 tests still OK, rc=0**. So the
mechanism is verified by me and by nothing in the repo. On this change the cell
it protects is the one that was a no-op for a whole review cycle, so it is the
cell most worth a guard. A three-line test asserting `PROFILES_DIR` is honoured
would have caught my no-op too.

The seeding is `emptyDir`-or-`PVC`/`subPath` in the plan's prose, and **there is
no initContainer manifest in it** — §8.3.2 part 2 says "the `/srv/aibot-profiles`
initContainer seed described in part 3" and part 3 describes it in one clause.
For the step whose whole purpose is to make the profile writable, the copy
command is the load-bearing part and it is the least specified. If the seed
runs on every pod start it also **reverts Scout's edit on any restart** — the
plan's step 4 says "or restart the pod once more (state which was done)", and
that restart now un-does the edit. Those two sentences contradict each other.

## 2. B2, the directive key — fixed, and the dispatch actually dispatches

`act["kind"]` → `{"type": kind}` plus the bound args, which is what
`_run_directive` pops (`agent.py:2031`, `dtype = params.pop("type")`). Verified
by running the real `bind_actions` output through the real method:

```
GOTO               handled=True _run_directive got [{'type': 'GOTO', 'target': 'chest'}]
EQUIP              handled=True _run_directive got [{'type': 'EQUIP', 'target': 'diamond_sword'}]
EQUIP_ALL          handled=True _run_directive got [{'type': 'EQUIP_ALL'}]
VAULT_STORE        handled=True _run_directive got [{'type': 'VAULT_STORE'}]
...
```

Mutant A (restore `act.get("directive")`) reddens 2 tests, rc=1 — I ran it, and
I get the same two they report. The fixture change from
`{"directive": {...}}` to `{"kind": ...}` is the right correction and their
comment on it says why in one line.

**The `dispatch:` line is printed only for `ran == 0`.** For a tick where the
script proposes two actions, the log names the first and says nothing about the
second — the count line above it says "2 action(s) this tick", so the tick is
not unaccountable, but the plan's §8.3.5 row 1 requires "the dispatch: line",
singular, and a two-action script would pass the gate on one line for two
actions. Scout sends one, so this does not bite this run; it is worth one word
in the plan so the next script does not inherit the ambiguity.

## 3. The defect the fix exposes — 6 of 10 agent-side kinds do not do what they say

**This is why I am not passing the run.** The pre-fix code dispatched nothing,
so this was invisible. Now every bound action reaches `_run_directive` directly
— but `_run_directive` sends a **mod directive** via
`api.set_directive(bot, dtype, **params)`. The agent-side kinds are not mod
directives. They are special-cased in `_l3_orchestrator_dispatch`
(`agent.py:901`), and that function is reached **only from
`plan_orchestrator`** (`:1370`, `dispatch_fn=self._l3_orchestrator_dispatch`) —
never from the script branch.

The plan states the opposite at §8.3.5 note (`:246`): *"`api.do` does not bypass
the mod: it resolves to `api.set_directive`, **the existing dispatch**."* The
validated set is `BINDABLE_KINDS = AGENT_SIDE_KINDS | MOD_DIRECTIVE_KINDS`
(`action_binding.py:48`) — **10 + 35 = 45** kinds accepted.

| kind | billed to the script as | what the script path does now |
|---|---|---|
| `EQUIP`, `EQUIP_ALL` | `api.equip_all` — the mod has **no** directive of this name | POST `{"type":"EQUIP"}` to a directive endpoint → mod rejects |
| `DROP`, `DISCARD` | `api.drop` — arg is an **item**, resolved to hotbar slots agent-side | mod receives `target: "dirt"` → rejects |
| `VAULT_STORE`, `STORE` | `api.vault_store` — no `target` needed | mod receives `VAULT_STORE` → rejects |
| `VAULT_WITHDRAW`, `WITHDRAW` | `api.vault_withdraw(target)` | mod receives it → rejects |
| `PROVISION_TERMINAL` | a terminal request + poll | mod receives it → rejects |
| `ASK_PLAYER` | asks L4 and waits up to 180 s | mod receives it → rejects |

Six names, nine spellings. For each: `_run_directive` catches the failure and
returns `{"success": False, ...}` — it does not raise — so `_run_script_tick`
does not fall through and the planner never runs. The script's tick is consumed
as "handled" by an action the mod refused.

**Is this reachable today? No, and that is the reason to fix it before the run
rather than after.** `scout.js` sends `{"kind": "STORE_ALL"}` only, and
`STORE_ALL` is a mod directive where the direct path is correct. So the run in
front of us is not endangered. But the binding *advertises* 45 kinds to any
future script, `BINDABLE_KINDS` is what its refusal message prints
("not in the agent's dispatch set (45 kinds: 10 agent-side, 35 mod)"), and the
next script that calls `api.do("EQUIP")` gets a refusal from the mod it can do
nothing with. Two-way fix, builder's call:
- route agent-side kinds through `self._l3_orchestrator_dispatch` (which maps
  `kind` → `type` itself, `agent.py:1012-1013`), or
- narrow `BINDABLE_KINDS` to the mod set on this path so the binding refuses
  them honestly at bind time, where a script can see it.

Either is small. Leaving it is the difference between "the script path works"
and "the script path works for 36 of the 45 things it says it allows".

**A related sentence that now reads wrong:** the plan's §8.3.5 note that
`api.do` resolves to `set_directive` "the existing dispatch" is false for both
the positive and negative cases — the existing dispatch is
`_l3_orchestrator_dispatch`, and `set_directive` is the fall-through at its end.

## 4. Smaller items — all four stand

- **Mount moved to `/srv/aibot-scripts`**, and the Dockerfile reason is given
  (`COPY . .` puts `agent/scripts/` at `/opt/aibot-agent/scripts`). Correct,
  and the plan's explanation is better than my finding.
- **`scout.json` key removed.** I could not find a consumer for it, so removing
  it removed a claim, not behaviour.
- **`_float_env` attribution fixed**, and they went further than I did:
  `6973c24` is **2 minutes after** `d45751d`, so it is not in the deployed image
  at all. I had written "post-deploy, not M2"; the tighter fact is "not in the
  image being replaced". Their wording ("a passenger, not a deliverable") is the
  right one.
- **`7fdbad9076381f43` recomputed independently** and matches.

**`HEAD 146 commits ahead`** — I did not check this and cannot cheaply: it is a
count against a branch tip that moves. The deployed-commit derivation is
theirs, it is the right shape, and they have now stated its limit themselves
(source identified, not a clean-tree build). That limit is the correct scope and
I am not going to hold a run for it: the plan's protection is that the new image
is built from the reviewed head and pinned by index digest, which does not
depend on knowing what the old image was built from — only on knowing it is not
the reviewed head.

---

## Summary

| item | verdict |
|---|---|
| `9222435` tree, suites | PASS — 108 OK, run by me |
| B1 profile path — diagnosis and `ls` on the pod | PASS |
| B1 `PROFILES_DIR` honoured, prod unchanged | PASS — verified three ways by me |
| B1 test for `PROFILES_DIR` | **GAP** — mutant B survives 108/108 |
| B1 initContainer seed vs "restart the pod once more" | **HOLD** — the two sentences contradict |
| B2 `kind` → `type` dispatch | PASS — mutant A reddens 2, run by me |
| B2 `dispatch:` line on multi-action ticks | note, not blocking |
| **agent-side kinds on the script path** | **HOLD** — 9 spellings accepted, resolved as mod directives |
| smaller items (mount, scout.json, `_float_env`, revision) | PASS |

The tree is good work. The HOLD is not a regression they introduced — it is a
pre-existing mismatch between what the binding accepts and what the script
branch can run, which the fix made reachable and which the plan's own sentence
denies.

Nothing deployed. No secret value printed. **No cluster fact verified from this
seat** except where I say the `ls` is theirs: the pod listing, the deployed
digest, and the 146-commit count are reports, not observations, and are marked
as such above.

*Numbers: 108 is the unittest tally printed above; 10 + 35 = 45 is
`len(AGENT_SIDE_KINDS)` and `len(MOD_DIRECTIVE_KINDS)` read from
`action_binding.py` at `9222435`; "6 names, 9 spellings" is those two frozensets
read directly, not counted by eye.*
