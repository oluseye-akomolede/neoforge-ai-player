# Review — M2 step 3 follow-up at `2b9d297`

**Row:** `qitem-20261111121443-77856143b05a765f`
**Verdict: import fix PASS (verified by running it). Parity subject: MY RULING WAS WRONG — corrected below.**

Revs: `2b9d297` (neoforge, `minecraft-wt-deepseek`).

---

## 1. Import path — PASS, and I closed their residual by running it

They fixed it in this change and then declined to claim it:

> "I have not run this in a genuinely clean 3.12 without the deps present, only
> verified the import graph. If you can run it, your run is better evidence."

**This seat is that clean environment.** Verified absent before running:

```
psycopg2: absent   uvicorn: absent   fastapi: absent   pydantic: absent
Python 3.12.3
```

`python3 -m unittest agent.test_script_client -v` → **Ran 12 tests, OK.** So the
blueprint is executed clean, not merely analysed. The residual is closed.

The fix itself is right and, more importantly, says *why*: the comment records
that `agent/` has no `__init__.py` so `agent` resolves to `agent.py`, which
drags in `psycopg2` and `uvicorn`. A future reader can't "tidy" it back to the
package import without reading the reason not to.

**Their method correction is the same defect class, and they caught it.** They
first tried a `meta_path` blocker using the legacy `find_module` API, which
3.12 ignores for nested imports — so the old, broken version also ran green and
the harness proved nothing. They caught it because the negative control passed
when it should have failed. That is an inert gate, the same shape as the thread
assertion in `1c6ee12`, found by the builder this time. Reporting it rather than
quietly discarding it is the right call.

---

## 2. Parity subject — MY RULING WAS WRONG, on the reason it gave

I ruled `STORE_ALL` and wrote that it "takes neither [target nor count], so the
comparison isolates the binding." They applied it faithfully. **The reason is
false**, and I found it by reading the behaviour rather than the planner:

```
StoreAllBehavior.java:63   targetedContainer = BlockPos.containing(
                              directive.getX(), directive.getY(), directive.getZ());
StoreAllBehavior.java:161  if (!isStorageBlock(level, targetedContainer)) {
StoreAllBehavior.java:162      bot.systemChat("Targeted container at ... is no longer a container", "red");
```

`STORE_ALL` **reads a target position and branches on it.** It is not
argument-free.

And the planner's own vocabulary contains **both** forms:

```
l3_planner.py:142   "search_and_loot":    (("AREA_LOOT", "STORE_ALL"), ("x","y","z","radius"))
l3_planner.py:143   "harvest_and_store":  (("FARM", "STORE_ALL"),      ("crop","count"))
skill_author.py:281 {"type": "directive", "kind": "STORE_ALL"}          # no coords
```

So a script path posting bare `STORE_ALL` and a planner path posting
`STORE_ALL` + coords take **different branches** in `StoreAllBehavior`. The
directive is the same type; the behaviour is not.

**Why this is worse than a wrong reason.** The observation point I chose —
`HttpApiServer.java:1356` — emits `accepted` + `directive.toMap()` from one
handler before any behaviour runs. A coords-bearing and a coordless `STORE_ALL`
therefore produce an **identical POST response while their effects diverge**.
The comparator I picked to be branch-free hides precisely the difference the
parity test exists to detect. I ruled a confound out of `CHANNEL` for taking
`target`/`count`, then ruled the same confound in for `STORE_ALL` because I read
the planner's tuple names instead of the behaviour's field reads.

**What still stands:** `IDLE` is still correctly excluded — `IdleBehavior.java`
has no log/chat/send, so it leaves no trace on either path. That part of the
ruling was checked by reading the file and it holds.

**Correction, and I am not picking a third name unilaterally.** Two honest
options, both cheap:

- **(i) Keep `STORE_ALL`, pin the argument form.** Require both paths to post
  the *same* coordinates, and assert the POST bodies are byte-identical. Then
  the shared branch is exercised and the confound is controlled rather than
  ignored. Needs a known storage block in the world at test time.
- **(ii) Pick a directive whose behaviour genuinely reads no positional args**
  and confirm that by `grep` of the behaviour's field reads, not by the
  planner's vocabulary. I will do this lookup if you'd rather not spend the
  turn on it.

My recommendation is **(i)**: it keeps everything already written, and the
same-coordinates constraint is one fixture detail, not a rewrite. But the plan
sentence "`STORE_ALL` takes neither" must go either way — as written it will be
quoted as the justification for the comparator.

---

## 3. Plan edits otherwise — PASS

`STORE_ALL` is now named in §3 and in §8.2 item 3, with the POST as the
observable and the absence-of-POST as the silence evidence. That closing of the
unnameable-subject gap is correct and is a genuine improvement: §8.2 no longer
defers to a section that named no subject.

`STORE_ALL` is `DirectiveType.java:27` — confirmed. The `IDLE` and `CHANNEL`
reasoning is recorded accurately, apart from the `STORE_ALL` arg claim above.

---

## Summary

| item | verdict |
|---|---|
| Import fix at `2b9d297` | **PASS** — 12/12 in a genuinely dep-free 3.12.3 |
| Their inert-harness disclosure | Correct, and the same class as `1c6ee12` |
| `STORE_ALL` named in §3 / §8.2 | PASS on the naming |
| The reason "`STORE_ALL` takes neither" | **WRONG — my ruling, my error.** It reads x/y/z |
| `IDLE` exclusion | Stands — no log/chat/send |
| Observation point `:1356` | Stands, but only once the arg form is pinned |

---

## 4. Follow-up at `0aaea2a` — correction applied, verified at source

I verified the retraction the same way I should have checked my own claim the
first time: by reading the behaviour, not the planner.

```
StoreAllBehavior.java:62   if (directive.hasLocation()) {
StoreAllBehavior.java:63       targetedContainer = BlockPos.containing(getX(), getY(), getZ());
```

The conditional form `hasLocation()` is more precise than my "reads x/y/z" —
coordinates are *optional*, which is exactly why both planner forms exist. The
builder's reading is right.

The plan now records my false sentence **as false and explicitly
not-to-be-quoted**, rather than deleting it silently. That is better than a
clean deletion: a future reader who finds the idea somewhere gets the
retraction with it.

**One gap remains.** §8.2 item 3 asserts the POST bodies are "byte-identical
between paths" but never says where the script path's coordinates come from.
They come from the script's own `api.do(directive, args)` (`M2-PLAN:246`), mapped
through `set_directive` (`api.py:428`). So the assertion **can** fail — the
comparator is not self-confirming, which was my worry. But the test must take
the script's arguments *from the script*, not hardcode them; if the harness
writes both bodies the assertion compares two things the harness wrote and
proves nothing. One sentence in §8.2 closes this, and it is the same
inert-gate failure we have now hit three times in this thread.

**Checked and does not bite:** `StoreAllBehavior.java:171` calls
`player.moveTo(targetedContainer…)`, so the coords form *does* move the bot —
the ground on which `MINE` and `PATROL` were excluded. It does not affect this
comparator because §8.2 compares the POST response, emitted at `:1356` before
any behaviour runs. Worth knowing that the exemption is positional, not
intrinsic.

---

## 5. Follow-up at `bcd2447` — gap closed, and a THIRD correction to my own evidence

The gap is closed correctly. §8.2 now says the test reads `STORE_ALL` and its
`x`/`y`/`z` out of the runner's `actions[]`, names the harness-writes-both-bodies
failure mode, and records the positional-not-intrinsic exemption. I verified the
`set_directive` claim too — `agent/api.py:437` really is
`if x is not None and y is not None and z is not None:`, all three or none.

**But I checked the wrong thing twice, and this time it is the evidence itself.**
I have twice cited `l3_planner.py:142-143` as showing "both forms are real in the
planner's own vocabulary". Read properly, it shows nothing of the kind:

```
139  _SEED_SKILLS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
142    "search_and_loot":   (("AREA_LOOT", "STORE_ALL"), ("x","y","z","radius")),
143    "harvest_and_store": (("FARM", "STORE_ALL"),      ("crop","count")),
```

The second tuple is the parameter list for **the whole two-step signature**, and
`_build_skill_extra(param_names, directives)` (`:270-272`) harvests those names
from *all* directives in the sequence and folds them into a `SKILL` extra. So
`("x","y","z","radius")` are `AREA_LOOT`'s parameters, and `("crop","count")` are
`FARM`'s. **`STORE_ALL` receives no parameters in either entry.** On the planner
path, `STORE_ALL` appears to be coordless; the only place a coords-bearing
`STORE_ALL` demonstrably exists is `skill_author.py:281`-adjacent authoring.

**Why it matters, and why it does not overturn the ruling.** The parity test
still works — but its force now rests on the *script's* choice of coordinates
raising a form the planner does not itself emit for `STORE_ALL`, not on both
paths naturally producing the same form. That makes the pinned-coordinates
assertion **more** load-bearing than the plan currently says: it is not holding a
natural argument form constant, it is constructing one the planner path may not
naturally have.

**What I am not claiming:** that the planner can never emit a coords-bearing
`STORE_ALL`. I have shown the seed table does not attach coordinates to it and
that the skill-collapse path folds params upward. A model emitting a raw
`{"kind":"STORE_ALL","x":…}` outside a seed match would still carry them. I did
not trace that path and am not asserting its absence.

**Recommendation:** before step 4 writes the test, confirm from a real planner
run which form the planner actually emits for `STORE_ALL`, and write the §8.2
expectation from that. If it emits coordless, pinning coordinates tests the
script against a form the planner does not produce, and the honest comparison is
either a different subject or an explicitly-constructed planner call.

**Method note on myself:** this is the third time in this thread I have ruled on
a name by reading the vocabulary that *references* it rather than the code that
*consumes* it. The `l3_planner` tuple looked like per-directive arguments; it is
a skill signature. Reading the consumer (`_build_skill_extra`) is what settles it,
and I should have done that the first time rather than after the builder had
already applied the reason twice.

---

## 6. Follow-up at `823c2a4` — the producer I did not trace, traced and verified

I declined to assert that the planner can never emit a coords-bearing
`STORE_ALL`. The builder traced it rather than leaving it open, and the answer is
better than either of us stated.

```
agent/agent.py:1622   _STORE_ALL_PATTERNS = re.compile(
agent/agent.py:1623       r"(?:store|dump|deposit|stash)\s+(?:all|everything|inventory)|STORE_ALL")
agent/agent.py:1888   if self._STORE_ALL_PATTERNS.search(text):
agent/agent.py:1889       return {"type": "STORE_ALL"}
```

**The pattern has no capture groups at all** — a bare boolean `search()`. So the
handler *structurally cannot* carry coordinates, whatever the input text
contains. That is stronger than "returns no coordinates": the code shape forbids
it, so this is not a case that happens to be coordless but one that cannot
become coords-bearing without an edit to the pattern.

**Step-4 gate: satisfied in the direction that matters.** No producer found in
agent code emits a coords-bearing `STORE_ALL`; the seed path is structurally
coordless. A raw model emission outside a seed match remains untraced, and
neither of us asserts it away. The plan's framing — that the test *constructs*
the argument form and proves "the two paths agree on the call the test wrote" —
is the correct and honest description of what that assertion has force to show.

**Third survivor, verified independently.** I grepped for the withdrawn claim
myself rather than accept the sweep: two hits, `:464` and `:523`, both naming
themselves as retracted. The rationale now reads "a single optional coordinate
triple with no formatting to normalise, and that triple is pinned rather than
relied on" — rewritten, not annotated.

`openspec validate coded-agents --strict` → valid, at `823c2a4`, rev printed by
the same invocation.

**Verdict: no open items from me on step 3.** The parity subject is named,
pinned, and its force honestly scoped; the import path runs clean in a dep-free
3.12; the thread gate fails when it should.

**Where the turns went, recorded because it is the durable lesson:** four of my
rulings in this thread carried a reason I had not checked by reading the
consuming code, and the builder caught every one — `STORE_ALL` "takes neither",
the "both forms are real" seed-table reading, and the pre-existing unreviewed
`load_profile`. The pattern is consistent: I read the table that names a thing
and skip the function that consumes it. The fix is not care in general, it is
one specific step — open the consumer before writing the reason, not after.
