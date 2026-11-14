# Review — `openspec/changes/ollama-think-control/` at `03ff511`

Reviewer: `minecraft-reviewer@minecraft`. Row `qitem-20261113194852-b6c380519c5e72d6`.
Read from `git archive 03ff511` into `/tmp/rev-03ff511` — not from a working tree.
Gateway read at `bcef0ca` (llm-gateway HEAD, worktree `minecraft-wt-qwen`).

## Verdict: NOT PASS — three findings, all closeable inside this change

The core of the change is right: one setting, an explicit top-level `think`,
an enumerating test, and a truncation rule that distinguishes `length` from a
genuinely empty answer. All three are correctly shaped and testable. What
follows are gaps in coverage of the change's own stated scope, not objections
to its design.

### F1 (blocking) — the eval runner's `/api/chat` call is missing from the scope, and it is on the model under test

`agent/output_evals/run.py:54` posts to `{cfg.endpoint}/api/chat` — a
hand-rolled `urllib.request` call with its own payload dict (`run.py:49-56`).
It is the **15th** `/api/chat` site on this rev; my grep returns 14 matches
because `agent/l3_planner.py:10` is a docstring line, leaving exactly 14 real
sites: brain×2, criteria_eval×1, planner×2, l3_planner×7, output_evals×1.

The spec's Impact line (`proposal.md:57-58`) names four modules and omits
`output_evals`. Task 1.2 names the same four. Task 1.4's enumerating test as
written would therefore pass at **14/14** while the eval runner still omits
`think`.

Why this is blocking rather than a follow-on: the handoff row this spec is
measured against (`qitem-20261113194717-c386a1082d087421`) asks for it
explicitly — "evals runner: a 'think' setting in the eval config so I can run
qwen3.8 think=false vs think=true on the same 75 cases" — and because when the
lead runs that comparison the eval runner's endpoint is
`http://ollama-l3.minecraft-test.svc.cluster.local:11434` against
`qwen3.8:27b-q4_K_M` (`evals/make-evals-configmap.sh:66`), i.e. **exactly the
thinking model in exactly the failing shape**. A think-on leg measured through
that runner without control is measuring the bug.

Also: `output_evals` is packaged standalone — `make-evals-configmap.sh:54-56`
copies only `output_evals/*.py` and `scorers/*.py` into the ConfigMap. So
`run.py` cannot import `agent/config.py`; the eval needs its own `think` key in
its own config file, not `AIBOT_LLM_THINK`. The spec should say so, or the
implementer will reach for the setting named in the requirement and cannot.

**Fix**: add the eval runner to Impact and task 1.2, add `think` as an
`evalconfig` key (surfaced in `describe()` like `endpoint`/`model`, since the
report is signed against the config), and make task 1.4 cover it. The existing
`evalconfig.py:4-10` docstring already establishes why this package keeps its
own config rather than borrowing the agent's.

### F2 (blocking) — `evalconfig.check_endpoint` uses `/api/tags`, so it does not catch a missing-model or thinking-on endpoint before the run

`evalconfig.py:104` probes `{endpoint}/api/tags`. That proves the endpoint is
up and the tag is present; it does not exercise a chat completion. Combined
with F1, a user could set `think: false`, get a model with `think` silently
ignored or dropped, and see every case come back unscorable with no signal
distinguishing "model has nothing to say" from "budget eaten by thinking".

This is the same failure class the spec's own Requirement 2 exists to catch,
one layer out. Not a duplicate of F1 — F1 is about sending the field, F2 is
about the probe that is supposed to refuse a bad run before it starts.

**Fix**: either extend the requirement to say the eval runner's readiness check
must send one tiny chat (a `num_predict: 2` `"Say OK."` call is already done in
`llm-gateway/app/main.py:142-147` for warming, so the pattern exists) and
report an empty-content/`done_reason=length` reply as a refused run, or scope
it out explicitly with a note saying the lead's comparison will catch it. Silently
leaving it unaddressed is the one option that reads as covered when it isn't.

### F3 (blocking) — Requirement 3's gateway change has nowhere to live: the gateway tracks no tests

`llm-gateway` at `bcef0ca` tracks seven files —
`.gitignore`, `Dockerfile`, `app/__init__.py`, `app/main.py`,
`llm-planner-spec/l3-planning-layer-spec.md`, `requirements.txt` — and **no
test file or test directory**. Verified by full `git ls-files` listing, not by
a failing grep.

Tasks 3.3 and 3.4 ("unit test: the forwarded Ollama body carries
`think: false`", "unit test: a request without `think` sends no `think` key")
are therefore not "the same pattern as `format`" — `format` has no test either.
The spec's claim at `spec.md:65` ("following the same path the shim already
uses for `format`") is true of the *code* path (`main.py:305`, `:392`) and
false of the *test* path, because there isn't one.

That matters because the spec then states the requirement in the strongest
form: "a client that sends `think` SHALL NOT have it silently dropped"
(`spec.md:67`), and the mechanism by which it was dropped is exactly a Pydantic
model that silently discards unknown fields. Without a test the same bug returns
on the next field anyone adds.

**Fix**: the change must bring up minimal test infrastructure for the gateway
(`pytest` + `httpx`/`ASGITransport`, or `TestClient`, depending on what
`requirements.txt` already pins) and say so in the change — otherwise task 3.3
is unbuildable as written and will quietly become a code change with no test,
which is the condition that produced the bug.

## Checked and correct

- **`think` at top level, not in `options`** (`spec.md:16-18`): matches Ollama's
  actual contract and matches the gateway's `format` handling (`main.py:305` vs
  `:392`, where `format` deliberately bypasses the `options` dict). Correct.
- **Explicit value, not omit-when-off** (`proposal.md:46-51`): sound reasoning,
  and the "testable without a thinking model to hand" claim holds given the
  body-enumerating test.
- **Requirement 2 both ways**: `content == "" and done_reason == "length"` is
  the correct predicate. Non-thinking models emit `done_reason: "stop"`; a
  genuinely empty answer from a thinking model with budget remaining also emits
  `"stop"`. I checked all eleven content-reading sites
  (`brain.py:32,67`, `criteria_eval.py:300`, `planner.py:143,300`,
  `l3_planner.py:425,785,834,885,920,1013,1129`) — every one discards the
  response dict after reading `content`, so adding the `done_reason` read is a
  local change at each site, not a refactor. Task 2.1 is accurate about scope.
- **No third thinking-capable path in the agent**: `openai_brain.py` is the L4
  OpenAI client (`openai_brain.py:23-24,39`) and is correctly out of scope;
  `semantic_memory.py:77` posts to `/api/embeddings`, which does not carry
  `think`; `script_tick.py:203` talks to the script runner, not Ollama.
  `l3_planner.py:10`'s claim that requests go through `OLLAMA_URL` and the
  gateway's `/api/chat` handles them "transparently" overstates it — the gateway
  is not in front of the agent's own `OLLAMA_URL`; it is the test path. That is
  handled by the existing prose separating test and prod at `proposal.md:28-34`,
  so it is not a finding — noting it so nobody reads the docstring as assurance.
- **`AIBOT_LLM_THINK` bool idiom**: `config.py:89,98,115,122` all use
  `os.getenv(...).lower() in ("true","1","yes")`; task 1.1's "existing
  bool-env idiom" is unambiguous. Correct.
- **Proposal's "15 call sites" against my 14**: `proposal.md:5` says "All 15 bot
  profiles" — profiles, not call sites. No discrepancy.
- **Ownership split** (agent vs gateway vs cluster) at `proposal.md:33-34,43-44`
  and task 4.1-4.2 is consistent with the handoff row's "I do every cluster
  step". Correct.

## Instruments

- `grep -rn "api/chat" --include=*.py` on `/tmp/rev-03ff511` → 14 lines, one of
  them `l3_planner.py:10` (docstring), so **14 real sites across 5 files**.
  Positive control in the same batch: `num_predict` grep returns 12 lines
  across 4 files, and manual enumeration of `requests.post(` returns 20 hits
  that include `output_evals/run.py` (via `urllib`) only after widening the
  pattern — which is how the eval runner was found.
- `git ls-files | wc -l` in `llm-gateway` → 7, listing shown above, zero test
  files. Positive control: the same command in `neoforge-ai-player` returns
  hundreds of files including `agent/tests/`.
- This is a spec review. No code was run, no test suite invoked, no cluster
  command issued. All claims are about file contents at the named revs.

## One thing I did not check

The lead's handoff row also asks for "a SKILL-is-a-valid-exec-kind" scorer fix
(`qitem-...-c386a1082d087421`). It is not mentioned in this spec, and the row's
earlier finding that `DIRECTIVE_KINDS` (37) and `_VALID_DIRECTIVE_KINDS` (35)
differ may or may not be the same issue. I am not filing that as a finding
against *this* change — it is a different repo path and a separate ask — but
whoever picks up the handoff should confirm it has an owner.
