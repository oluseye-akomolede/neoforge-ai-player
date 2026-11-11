# Review — M2 plan `4bf3ce3` (re-review of the `7d4c33a` additions)

**Reviewer:** minecraft-reviewer@minecraft
**Rev under review:** `4bf3ce3` (full: `4bf3ce389d446d9a26228721067ea64628c6c16b`)
**Parent:** `6b3a4d2` (my previous review commit)
**Verdict:** **PASS** — both fixes landed correctly. One factual defect in the new
text, non-blocking but it must be corrected because it names a function nothing calls.

## 1. Both requested fixes are in

**Duplicate fence removed.** `the script source` now occurs twice, at `:420` (the
annotated block) and `:454` (the ConfigMap YAML placeholder) — the second is a
different thing, not a repeat. Fixed.

**Per-bot mechanism named, and the wrong answer stated out loud** (`:547-570`).
This is better than what I asked for. I asked for the mechanism; they also wrote
down *why the obvious alternative is a trap*: "a `RUNNER_URL` env var would cut
off every bot while looking like it satisfied the lead's condition", and closed
with "a proof that passes while secretly cutting off every bot". That is the
sentence that stops the next implementer, and it was not in my review.

## 2. One factual defect: the cited loader is the unused one

`:556` says:

> Per-bot state comes from the **profile dict** instead... `config.load_profile()`
> (`:111`) reads the single `PROFILE_PATH`

`config.load_profile()` **does exist** at `config.py:111` exactly as cited. But
it has **no call sites anywhere in `agent/`**:

```
$ grep -rn "load_profile\b" agent/ --include=*.py | grep -v load_profiles
(nothing)
```

The live startup path is a *different, plural* function:

- `agent.py:3186` — `def load_profiles():` — "Load all profile JSON files from
  the profiles directory", listing `agent/profiles/*.json` and returning the list.
- `agent.py:4244`, inside `run()` (`:4130`) — `profiles = load_profiles()`, then
  `for profile in profiles: runner = BotRunner(profile)`.

### Why this matters beyond a citation

The plan's argument is "`load_profile()` reads the *single* `PROFILE_PATH`, so
per-bot state must come from the profile dict instead." The conclusion is right,
but the premise points at dead code, and the live loader supports a **stronger**
version of the same point:

`load_profiles()` reads **every** file in `agent/profiles/`, so adding
`runner_url` and `script_path` to `agent/profiles/scout.json` is picked up with
**no code change to the loader at all**. The plan says the fields are "consumed
alongside the existing profile keys", which is true, but a reader checking it
against `load_profile()` would find a function that never runs and could
reasonably conclude the plan is describing a path that does not exist.

Corrected form: cite `load_profiles()` (`agent.py:3186`, called at `:4244`) as
the loader, and note that it needs no change — only `BotRunner`'s consumer
(`agent.py:155`) does, to read the two new keys.

## 3. Accepted correction to my own review

The builder is right that `BotRunner.__init__` is at `agent.py:155`, not `:153`.
`:153` is the class statement; `:155` is the docstring line, with `:157` the first
executable line. My earlier review said `:155-157` in the table but `:155` in
prose without that precision, and their citation is the accurate one. Noted
rather than disputed.

## 4. Verification performed

- `openspec validate coded-agents --strict` → **valid, rc=0**, run at
  `4bf3ce389d446d9a26228721067ea64628c6c16b` (the rev printed by
  `git rev-parse HEAD` in the same command). Their claim that they committed
  before validating holds for this rev.
- The three findings they re-verified independently (no per-bot env, `replicas:
  1`, no `url`/`runner`/`endpoint` in any profile) — I confirm all three again
  at `4bf3ce3`.
- Duplicate fence: confirmed absent.
- Cited line numbers `config.py:111` and `agent.py:155`: both resolve as
  described.

## 5. What this PASS does not cover

Plan-only commit; no code ran and no probe was taken. I did not re-read the full
539 lines — §7's file list and §8's proof remain untested claims until step 2
executes. The cluster facts (`aibot-agent-test` 1/1, `mindcraft/aibot-agent`
scaled to 0/0) remain the builder's reads; **this seat has no `kubectl` and no
kubeconfig**, so I have not confirmed them and do not imply otherwise.
