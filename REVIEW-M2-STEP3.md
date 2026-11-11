# Review — M2 step 3 (`f131fa5`)

**Verdict: the bounded call PASSES. The 4.4 thread assertion is worse than the
builder fears — it cannot fail. On the parity subject I rule for (a), but the
section must be rewritten, not annotated, and §8.2 inherits the same defect.**

---

## 1. `call_runner` — PASS

`script_client.py:139`. The bound is passed explicitly and the fallbacks are
distinct. I checked the claim that matters — that dropping the argument cannot
silently inherit 5 s — at its source: `api._post` has `timeout=5` at `api.py:33`,
and `call_runner`'s `timeout=SCRIPT_TIMEOUT` (0.3) is used both in the signature
and in the forward to `poster(...)`. The default cannot be reached by omission.
`test_script_timeout_is_300ms` pins it. Correct.

Three fallback states plus `script` are reported rather than raised, and
`actions` is empty on every fallback. That is the right shape: a half-applied
action list would be worse than none, and the caller's job is to run the planner,
not to handle exceptions.

**The fallback taxonomy is right and one branch deserves naming as good.** Both
`ConnectTimeout` and `ReadTimeout` map to `fallback_timeout` with the reason
stated in the comment: accepted-then-silent and refused-after-connect are
indistinguishable to the bot, and it must not wait to tell them apart. That is a
deliberate loss of information where the information has no use.

---

## 2. The 4.4 thread assertion — the builder's instinct is right, the defect is larger

They asked me to scrutinise:

```python
self.assertFalse(
    [t for t in threading.enumerate() if t is not threading.current_thread()
     and t.is_alive() and "requests" in (t.name or "").lower()],
    "a requests thread is still alive after the bound")
```

They framed it as "`no thread named requests` is a weaker check than `the
waiting thread was released`". **It is weaker than that: it cannot fail at all.**

Two independent reasons, both measured:

1. **`requests.post` is synchronous — it creates no thread.** Probed: a
   blocking `requests.get` against a dead port adds **zero** new thread names
   (`set()`). The condition `"requests" in t.name` therefore has no candidate
   to match, ever.
2. **Even a leaked thread is not named `requests`.** A `threading.Thread` gets
   `Thread-1`, `Thread-2`. Probed: a deliberately hung thread is named
   `Thread-1 (hang)` and the assertion **does not find it**.

Mutant, run directly: with a thread genuinely hung and alive, the expression
returns `False` — the test passes while the hang is present. The assertion only
fires for a thread someone manually named `requests-something`, which `requests`
never does.

**So this is a passing gate that is inert** — the same class I have been filing
on others all session, and it is the one assertion the builder singled out as
the one they would want checked. Credit where due: they flagged it unprompted
and asked me to say so rather than let them claim more than it shows.

**The behaviour it was meant to guard is nonetheless correct.** I drove the real
path (accepts, never replies): `state=fallback_timeout`, elapsed **0.431 s**
against a 0.3 s bound, `requests` threads alive: **0**, `threading.enumerate()`
back to `['MainThread']`. The bound works and nothing leaks. **The test does not
prove either of those things**, because the same result is produced whether or
not they are true.

**Fix:** compare `threading.enumerate()` before and after and assert the set is
unchanged (minus the test's own helper threads), or assert on the specific
helper thread's liveness. Any check whose subject is "the set went back to what
it was" can fail; one keyed on a name that never occurs cannot.

---

## 3. The parity subject — SAY is correctly found absent, and the section is now self-contradictory

**The factual claim is right and I verified it independently.** With a positive
control first (the same grep does find `CHANNEL` at `DirectiveType.java:13`),
`SAY` is absent case-insensitively. Recount of the enum: **37 constants**;
`DIRECTIVE_KINDS` **37**; set difference **empty in both directions**; `SAY not
in enum: True`. `api.py:217` is `chat(bot, message)`, a separate endpoint, as
stated. The finding is correct.

**The correction block is good. The prose under it was not updated.** Below the
"SAY is not a DirectiveType" block the section still reads:

- "It is **the best parity subject**" — of `say`
- "the bot reaches the **`say` directive** through the existing agent code"
- "the same `say` arrives via **`api.say`** from the runner"
- "**Why `say` and not `MINE`**"

The section now asserts a thing cannot be the subject and then specifies a
method whose entire subject is that thing. An annotation above contradictory
instructions is worse than the original error, because a reader reasonably
trusts the corrected block and then executes the stale method. **It must be
rewritten so one account of the subject survives, not two.**

---

## 4. My ruling on the three options: (a), with a condition the plan does not state

**I rule for (a) — pair the `chat` endpoint on both paths — but not for the
reason the builder gives, and it does not work as currently specified.**

The builder's reasoning is that (a) "tests the thing the plan actually wanted —
that a script-produced effect equals a planner-produced one". I checked whether
that survives contact with the code, and it does not, as written:

**Every planner-path `api.chat` is an aside, not an action.** The call sites are
`agent.py:359` (acknowledging a memory store), `:374` (work area set), `:394`,
`:470` ("On my way"), `:479` ("Stopping"), `:1214` (a chat reply), and
`sessions.py:230, :391` (session chatter). The planner's action output is a
`DirectiveType`; it never emits speech as an action. So "the planner path
produces a `say`" has no referent — there is no planner path that says
something *as its action*, only asides around an action.

**Consequence:** a naive (a) compares `api.chat(...)` against `api.chat(...)` —
the same function called from two places. That proves the endpoint works, which
was never in doubt, and proves nothing about the script→action binding. It is
the tautology shape of a test that constructs the expected value with the code
under test.

**So (a) is right only as a two-layer comparison**, which is the thing the plan
wants and did not name: the **script path must reach the effect through the
runner and the action-binding layer**, while the **planner path reaches it
through the existing directive dispatch**, and the *observable game-log line and
API sequence* must match. If both paths call `api.chat` directly, there is no
binding under test and the check is vacuous.

**Why not (c).** The builder offers (c) as the cheap fallback. It does not
escape: §8.2's game-side evidence is literally "the **`say` line** in the
server log", and §8.2 is the proof that already depends on `say`. Dropping 3.3
into 8.2 moves the phantom subject rather than removing it. If `say` is not
constructible at 3.3 it is not constructible at 8.2 either, and 8.2's evidence
item 3 needs the same correction.

**Why not (b).** `CHANNEL` and `STORE_ALL` are real `DirectiveType`s and would
give a genuine directive-parity check, but the builder is right that it tests
something narrower than the milestone's claim, and `CHANNEL` carries a
`target`/`count` the planner path formats differently (`l3_planner.py:142-146`),
adding a confound. Keep it as the later, separate check — the plan already says
`MINE` parity is "worth doing, but as a separate, later check", and `CHANNEL`/
`STORE_ALL` belong in that slot.

**What I want before step 3 is called done:**
1. `:413-428`'s options block resolved into one instruction; the `say` method
   prose below it rewritten or deleted so only the chosen subject remains.
2. The chosen (a) specified as a **two-layer** comparison (script→runner→binding
   vs planner→dispatch), not `api.chat` vs `api.chat`.
3. §8.2 evidence item 3 (`:640`) corrected to match whatever 3.3 becomes.
4. The 4.4 thread assertion replaced with one that can fail.

Items 1-3 are plan text; item 4 is code and is the only blocker on the tests.

---

## 5. Two notes not affecting the verdict

- **I could not run the suite as committed.** `test_script_client.py:19` does
  `from agent.script_client import …`, and because `agent/agent.py` exists,
  `agent` resolves to the **module** `agent.py`, which pulls in `psycopg2`,
  `uvicorn`, and the whole runtime. Neither is installed here. `script_client`
  itself imports only `__future__` and `requests` (AST-checked) — the coupling
  is in the test's import path, not the module. The builder reports the suites
  green; **I verified the behaviour by loading `script_client` directly and
  driving the real path, not by running their suite.** That is a scoped
  verification, not a suite run, and I am not claiming their green.
- `openspec validate coded-agents --strict` at `f131fa5`: the builder reports
  valid, rc=0, rev printed in the same command. I did not re-run it from a tree
  that validates this change; on report, not verified by me.

Nothing deployed, prod untouched.
