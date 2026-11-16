# Review — M2 step 3 follow-up (`1c6ee12`)

**Verdict: both findings fixed and verified. One open item left, and I rule on it
here rather than leave it to step 4. Plus an answer on the import-path question.**

---

## 1. The thread assertion now fails on the condition it names — PASS

`1c6ee12` replaces the name-filter with:

```python
before_threads = set(threading.enumerate())   # captured BEFORE the `with`
...
after  = set(threading.enumerate())
leaked = after - before_threads - {threading.current_thread()}
```

**I ran the mutant myself rather than accept the report.** A thread started and
never joined, default name:

| | catches the hang? |
|---|---|
| old check (`"requests" in t.name`) | **False** — `[]` |
| new check (set delta) | **True** — `['Thread-1 (wait)']` |

And after releasing it, the new check goes clean (`False`). So the gate now fails
on a real leak and passes on a real release — it is a working gate, not
decoration.

**The capture point is correct, which was the easy thing to get wrong.**
`before_threads` is taken *before* `with _NeverReplies()`, so the helper's own
thread is a legitimate delta, and `__exit__` joins it (`join(timeout=2)`) before
the assertion evaluates. If `before` had been captured inside the `with`, or the
join were skipped, the test would fail on its own fixture. Neither happened.

One residual, not a defect: `join(timeout=2)` returns on timeout without error,
so if the helper ever failed to exit within 2 s it would appear as a leak and the
test would red. That is the correct direction — it over-reports a fixture
problem rather than hiding one.

---

## 2. The parity section is now one account — PASS

`SAY` no longer appears as the subject anywhere. Swept the whole file: 27 `say`
hits remain, and I checked each class of them:

- `:253` `| say | the existing chat-send path (api.py:217 chat) |` — this is the
  **runner action** table from §3.2, where `say` is a legitimate action *name*
  that produces a chat call. Not the parity subject. Correct as written, and the
  note under it states the distinction explicitly.
- `:256` "`api.say` is a **runner** action (`binding.js:253`), not a mod
  directive — it produces a `chat` call, never a `DirectiveType`." Correct, and
  it is the sentence that prevents the next reader from repeating the error.
- `:463`, `:784`, `:804` — historical records of the correction itself. Correct
  to keep.
- The rest are prose uses of the word ("says", "what its script says"). Not
  referents.

**The ruled section reads as one instruction now:** subject is the binding; a
path-vs-route table; the vacuity warning stated in its own words ("If both paths
call the same helper directly, there is **no binding under test**"); (b) and (c)
rejected with reasons. The self-contradiction is gone.

**§8.2 item 3 is corrected**, which was the dangerous one: it now reads "the
observable effect of that action in the server log, matching §3's parity result",
not "the `say` line". The pointer from §3 to §8.2 is honest — I opened §8.2 and
the change is really there.

---

## 3. One item remains open, and it blocks step 4: **no concrete parity action is named**

§3 now says the parity action "must be a real `DirectiveType` with an observable,
non-movement effect" and that "the first proof needs the smallest one that still
crosses the binding" — but **it does not name which one.** §8.2 item 3 defers to
"§3's parity result", so 8.2's game-side evidence has no concrete observable
until §3 names one. That is the same phantom-shaped gap the section was just
fixed for, one level up: a requirement with no referent.

**I checked the candidates against the code rather than reasoning about them:**

- `IDLE` — has `IdleBehavior` (`BehaviorFactory.java:58`), but
  `IdleBehavior.java` contains **no log, chat or send call**. It produces no
  observable effect. It cannot be the parity subject.
- `MINE` — excluded already, movement confound. Agreed.
- `CHANNEL` / `STORE_ALL` — both real (`BehaviorFactory.java:44`,
  `SkillOutputResolver.java:105`), both carry `target`/`count` formatting
  (`l3_planner.py:142-146`) that adds a confound, and neither obviously emits a
  distinct log line.

**My ruling: `STORE_ALL`, and the observation point is the API response — the
mod's `{"status":"accepted","directive":{...}}`, not a behaviour log line.**

Reason, from `HttpApiServer.java:1356`: the directive POST returns
`{"status":"accepted","directive":directive.toMap()}`. That is emitted on **both**
paths, by the same handler, and is a structured, comparable artefact. Anchoring
the parity assertion on it means the check does not depend on whether a given
behaviour happens to log — which is exactly what made `IDLE` unusable when I
tested it. `STORE_ALL` is chosen over `CHANNEL` because it takes no `target`, so
the formatting confound disappears.

**Concretely, §3 and §8.2 item 3 should both say:** the comparator is the
`directive` object in the POST response (plus the API call sequence), and
`STORE_ALL` is the effect. That removes the last unbound noun and lets 8.2 cite a
real observable.

I am ruling rather than leaving three options open because you asked me to before,
and because an open subject in step 3 becomes an unbuildable test in step 4.

---

## 4. Your question: fix the import path now, in this change

You asked whether to fix `test_script_client.py:19` now or as a follow-up.
**Fix it now, in this change.** Reasons:

1. It is a **one-line** change with no behaviour risk: the test should load
   `script_client` by path (`importlib.util.spec_from_file_location`), or the repo
   should gain `agent/__init__.py` so `agent` stops resolving to `agent.py`. I
   used the first in my probe and it works.
2. A test that only runs where the full agent dep tree (`psycopg2`, `uvicorn`,
   psql client libs) is installed **cannot be run by the next reviewer or in CI**,
   which is how a green-on-one-machine suite stops being evidence.
3. Leaving it as a follow-up means the next gate on this file has the same
   blind spot I hit — and I had to decline your green for exactly that reason.

The behaviour checks themselves are unaffected; this is purely about the file
being runnable where the change is reviewed.

---

## Summary

| item | verdict |
|---|---|
| 4.4 thread assertion | **PASS** — mutant-verified, catches a leak the old check missed |
| Parity section rewrite | **PASS** — one account, no `say` referent, §8.2 corrected |
| Concrete parity action named | **OPEN** — ruling above: `STORE_ALL`, compared on the POST response |
| Test import path | **Fix in this change** |

Nothing deployed, prod untouched. As before, I verified the assertion by
reproducing it in isolation and driving the real path; I did not run your suite
(no `psycopg2`/`uvicorn` here), so I am not endorsing its green.
