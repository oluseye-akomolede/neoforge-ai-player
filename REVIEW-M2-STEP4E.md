# Review — `9a3c28e` (run steps and rollback rewritten to the bindings design)

**Row:** `qitem-20261111133655-a8f208d2a3b3d069` (handed back in prose; no row names this rev)
**Verdict: PASS on the design. One HOLD — step 2's verification command cannot run.**

Measured at the rev from a clean `git archive` export. Rev printed in the command
that produced each number.

---

## 1. The profile-edit procedure is correctly abandoned

The old part 3 edited Scout's profile to add a `script` key. It failed twice on
TEST — once as a no-op on the PVC copy, once reverted by the emptyDir seed on pod
recreate. Bindings replace it, and §8.3.2 now says so with the failure history
beside it. That is the right correction and it is recorded rather than quietly
swapped.

## 2. The resolver states match the plan's ordering claim — verified

§8.3.3 claims step 1 is "provably inert". I ran the resolver in all three states
the ordering produces, using the suite's own stub set:

```
STEP1  SCRIPTS_DIR set, no bindings.json  -> None   (+ "no bindings at …; this bot runs the planner")
STEP4  bindings.json present              -> '/tmp/…/scout.js'
UNSET  C1 refusal                         -> None   (+ "SCRIPTS_DIR is not set; script mode disabled …")
```

So step 1 truthfully claims nothing binds, step 4 truthfully claims Scout binds,
and the C1 refusal behaves as reviewed. **The ordering argument in §8.3.3 is
sound against the real code**, not merely plausible.

## 3. The image row is fixed properly (closes my `e14c284` HOLD)

The stale `1b74ae7b…9506a4` is now marked **dead** with the reason, and the new
`a97ae5a7…b6b2e6` carries three independent registry reads. I checked the one
thing that matters for "reviewed code in the image":

```
3887e79 contains 01e9eaf          : YES (git merge-base --is-ancestor)
commits after 3887e79 to 9a3c28e  : 2 — e956eff, 9a3c28e, both M2-PLAN.md only
```

The image is built from a rev that contains the reviewed fix, and everything
since is documentation. That is a proper pin.

## 4. Env names match the code

`RUNNER_TOKEN` is exactly the name `config.py:22` reads and `script_tick.py:51`
uses; `SCRIPTS_DIR` matches `agent.py`; `SCRIPT_RUNNER_URL` matches
`config.py`. The token is `valueFrom.secretKeyRef` with key `minecraft` — which
is also the `game_id` the runner checks the token against (`server.js:157`), so
a wrong key would 401 on every tick. Named by reference, never a literal.

## 5. HOLD — step 2's verification command raises `AttributeError`

§8.3.3 step 2 calls itself "the check that matters":

```
python3 -c 'import agent; print(agent._bound_script_path("Scout"))'  -> None
```

`_bound_script_path` is an **instance method** on `BotRunner`
(`agent.py:2667  def _bound_script_path(self):`). There is no module-level
function of that name. Run at the rev:

```
module has attr:      False
BotRunner has attr:   True
literal plan command -> AttributeError: module 'agent' has no attribute '_bound_script_path'
```

The operator runs this in-pod after the restart, at the one point the plan says
distinguishes "inert" from "silently doing something". It cannot execute. An
operator who hits an `AttributeError` at a verification step has to decide on
the spot whether that is the feature or the command — and the whole run's
ordering rests on this observation being real.

**Fix:** construct the runner, e.g.
`
python3 -c 'import agent; r=agent.BotRunner.__new__(agent.BotRunner); r.name="Scout"; print(r._bound_script_path())'
`
or expose a module-level helper `bound_script_path(name)` and call that. The
second is better for a run plan: one line, no `__new__` idiom in an operator's
terminal. Note `__new__` is needed because the real constructor opens sockets
and threads — same reason the test file does it.

This is the second time in this change that a verification step named an
observable that does not exist on the surface it names. The difference here is
that it fails loudly (`AttributeError`) rather than silently, which is why it is
one command away from passing.

## 6. Not verified

Every cluster fact: the deploy at `9de2a68`, `1/1`, five bots ticking, the
registry reads behind `a97ae5a7…b6b2e6`. No `kubectl` on this seat. The digest
and its provenance are taken as reported; what I verified is that the rev it
names contains the reviewed code.

---

## Summary

| item | verdict |
|---|---|
| Profile edit abandoned for bindings | **PASS** — failure history recorded |
| §8.3.3 ordering is inert at step 1 | **PASS** — resolver run in all three states |
| Image digest pin (my `e14c284` HOLD) | **PASS** — old marked dead, new carries reviewed code |
| Env names and token reference | **PASS** — all match source; key matches game_id gate |
| Step 2 verification command | **HOLD** — `AttributeError`, method not module function |
| Run/rollback prose | PASS on read; cluster facts unverified here |

Nothing deployed. No build or push by me. No secret value printed or read.
