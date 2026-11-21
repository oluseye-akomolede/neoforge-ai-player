# Review: 8521f73 — script prompt entry fields (4.5) + planner script source logged at bind

Date: 2026-11-21 · Reviewer: minecraft-reviewer · Rev: `8521f73` (branch `minecraft-wt-deepseek`)
Row: `qitem-20261121232200-d95bd60655377caf`

**Verdict: PASS.** One note (no action required) and one correction to my own
process, below.

## What was verified, by running it

### Producer shapes — all three cited line numbers resolve at `8521f73`

Read at the reviewed rev, not at HEAD (my worktree was at `41d39ff`, which lacks
`fb313cd`; see "Instrument failures"):

- blocks `{id, block, position}` — `NearbyBlockIndex.java:82-84`. `id` is
  `BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString()`, i.e. the
  namespaced registry id as the prompt states. `block` is the display name.
- mobs `{type, name, position, distance}` (plus `health` on a living entity) —
  `BotPlayer.java:883-888`, verbatim.
- items `{slot, item, count, display_name, max_stack_size}`, plus
  `durability`/`max_durability` only when `stack.isDamageableItem()` —
  `BotPlayer.java:1000-1006`, verbatim.

`id` also exists on an inventory item, but as an *enchantment* id nested inside
`enchantments[]` (`:1011`), never as the item identity. The prompt's warning
that `items[0].id` is `undefined` is correct, and the distinction is worth
having: a planner that reached `enchantments[].id` successfully would otherwise
read this as "`id` works on items".

### 4.5 KILLS test, applied literally

Mutating the mob identity field `type` → `id` at `planner.py:82` reds exactly
two tests (`test_each_lookup_shape_names_its_identity_field`,
`test_no_shape_substitutes_id_for_its_own_identity_field`), real rc=1 read
unpiped. A second mutant shape (drop `, NOT \`id\`` from the item line) reds one.
So the shapes are pinned per-field, not merely present — a presence-only test
would have stayed green, as the builder said.

### Bind-time logging

Removing the `planner script source` print reds exactly the two substantive
tests (`test_the_source_is_logged_with_bot_and_hash`,
`test_a_long_script_is_clipped_and_says_so`) and correctly leaves the two
absence-assertions green. Real rc=1.

### The hand-written claim — driven end to end, not read off the test

The builder said they could not drive a real hand-written binding. I did, using
the suite's own module stubs to load the real `agent.py`: with `SCRIPTS_DIR` set
and a `bindings.json` naming the bot, `_bound_script_path()` resolves to
`<dir>/scout.js`, `_bind_planner_script()` returns `False`, `_planner_script`
stays `None`, and the only log line is the "hand-written binding is deployed;
keeping it" message. **No source is echoed.** The early return at
`agent.py:3517-3523` is genuinely first, before the dry tick and before the
adopting print. Claim holds.

### Suite and specs

- 298 tests across the seven declared suites: **OK, rc=0**, read unpiped.
- `openspec validate script-lookups-and-results --strict` → rc=0, valid.
- `openspec validate ai-written-scripts --strict` → rc=0, valid.
- Both mutants restored; `sha256sum -c` OK; `git diff --stat 8521f73` empty.

### Cross-repo citations

- `MAX_SOURCE_BYTES` is real: `agent-script-runner/src/main.js:51`,
  `export const MAX_SOURCE_BYTES = 64 * 1024`, enforced at `:192` and `:265`.
- The spec's no-secret argument cites `engine.js:2-12`; that resolves in the
  same repo and does declare "No filesystem and no network", with the absence
  described as measured rather than assumed — matching the spec's "the sandbox
  has no filesystem, no network, and no environment access".

## Answers to the reviewer questions asked

**(1) Is 4096 defensible, and should "about 4 KiB" be an exact number?**

Defensible, and leave the spec wording as it is. Against the real 64 KiB bound
the cap is a 16× reduction, and the requirement's purpose ("a log line must stay
readable") is satisfied. The marker is bounded: measured worst case is 61 bytes
on top of the cap (`... [script truncated at bind: 61440 of 65536 bytes omitted]`),
and a 4096-byte cut through a multi-byte character drops the partial char
(`decode("utf-8", "ignore")`) so output stays ≤ cap+61. The test at
`test_agent_script_branch.py:2030-2035` derives its threshold from
`SCRIPT_LOG_CAP` rather than hardcoding 4096, so tightening or loosening the
constant later cannot silently diverge from the spec. Pinning "about 4 KiB" to
an exact number in prose would buy nothing the test does not already give.

**(2) Is hand-written-does-not-log actually reached?** Yes — see above.

## Note (no action required)

`_script_excerpt` clips on a byte boundary and discards the partial character.
That is the right choice here, but the marker says "N of M bytes omitted" while
the returned string may also have dropped up to 3 bytes of a split character.
At these sizes it is not worth changing; recording it so nobody later reads the
byte arithmetic as exact.

## Correcting my own process, not the commit

Three times this turn I nearly filed a finding against this commit on the
strength of a query that could not have answered it:

1. I ran `find`/`sed` for `NearbyBlockIndex.java` in a worktree at `41d39ff`,
   which predates the commit that introduced it, saw nothing, and was about to
   write "the cited file does not exist". Re-reading at `8521f73` found it
   immediately, with the exact shape cited.
2. I grepped `MAX_SOURCE_BYTES` in this repo and called it phantom. It is real —
   in `agent-script-runner`, a different repository. A constant that is cited
   correctly but lives elsewhere is not a phantom citation.
3. My first attempt at the suite reported `RC=0` off a pipeline; the runner's
   own rc was 1. Same pipe-reports-tail's-status error recorded before.

All three were caught by a positive control disagreeing with me, which is the
only reason they did not become findings. The builder's citations were correct
in every case.

## Files

`agent/agent.py` (+38), `agent/planner.py` (+10),
`agent/test_agent_script_branch.py` (+74), `agent/test_script_prompt_kinds.py`
(+38), `openspec/changes/ai-written-scripts/specs/bot-coded-agents/spec.md`
(+44), `openspec/changes/script-lookups-and-results/tasks.md` (4.5 ticked).
