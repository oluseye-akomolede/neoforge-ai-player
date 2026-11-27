# AI Player bot memory: facts for the blog post of Wed 12-02

Source of truth: the public repo https://github.com/oluseye-akomolede/neoforge-ai-player at
commit `6d990e7` (2026-11-27). Every `file:line` below refers to that commit. Paths are
relative to the repo root. Link form:
`https://github.com/oluseye-akomolede/neoforge-ai-player/blob/6d990e7/<path>#L<n>`.

The writer drafts from this file only. If a claim is not here, don't make it.
Numbers marked **(no public source)** must not appear in the post as fact.

Frame (owner): what the project is, what it is for, what it is good at, then memory in depth
with a diagram. Not a debugging story.

**Read section 7 before drafting.** The 11-11 topic note (two tiers, a hot cache of 200,
pgvector, a shared pool "so bots learn from each other", near-duplicates "merged") came from
an internal architecture doc. Several of those claims are not what the code does today, and
one of them changes the story: the planner the live bots use does not read the vector memory.
Section 8 suggests a framing that stays true.

---

## 1. What AI Player is (keep it short and link the 11-18 post)

- A NeoForge 1.21.1 Minecraft mod plus a Python agent that puts AI-controlled players on a
  server. Full facts: `docs/blog/ai-player-architecture-facts.md` (the 11-18 post). Link it,
  don't repeat it.

## 2. The bot has three memories, not one

| Memory | What it holds | Where |
|---|---|---|
| Notebook | Short text notes, one JSON file per bot, max 50, de-duplicated by exact text | `agent/memory.py:31-41` |
| Semantic (vector) memory | Embedded sentences in Postgres + pgvector, with an in-process hot cache | `agent/semantic_memory.py` |
| Plan memory | Whole plans that finished successfully, replayed for the same task | `agent/plan_memory.py:1-22` |

- The notebook's last 20 notes go into the bot's system prompt (`agent/prompts.py:155-156`).
- The vector memory module describes itself as two levels, "L1: In-memory vector cache" and
  "L2: pgvector database" (`agent/semantic_memory.py:4-6`).
- A bot flagged `ephemeral` skips the vector memory entirely (`agent/agent.py:612-613`); if
  Postgres can't be reached the bot runs without it (`agent/agent.py:618-620`).

## 3. What gets stored as a vector memory, and when

Four categories: location, instruction, knowledge, event (`agent/semantic_memory.py:8-12`).
Every write site at `6d990e7`:

| Trigger | Stored text | Category | Where |
|---|---|---|---|
| A player types `@bot remember: <text>` or `@all remember: <text>` | the text | keyword guess: "at "/"near "/"location"/"coords" -> location; "always "/"never "/"rule"/"instruction" -> instruction; else knowledge | `agent/agent.py:730-736`, `761-781` |
| Same command, second copy | `(from player <name>) <text>` into the **shared** pool | same | `agent/agent.py:775-777` |
| A player types `@bot area: <description>` | `[instruction] My designated work area: ...` | instruction | `agent/agent.py:783-796` |
| A MINE directive succeeds with >0 blocks | `Mined <n>x <block> near (x, y, z)` | location | `agent/agent.py:2911-2913`, `3197-3205` |
| A CRAFT directive succeeds | `Successfully crafted <item>` | event | `agent/agent.py:3206-3208` |
| An action fails in the step-execution loop | `Action '<a>' with params <p> failed: <error>` (metadata `type: error`) | knowledge | `agent/agent.py:4839`, `4855`, `4928-4935` |
| One-off seeding script | 65 crafting facts into the shared pool | knowledge | `agent/seed_item_memories.py:17-108`, `116-123` |
| Dashboard import endpoint | memories posted to it | as given | `agent/dashboard/server.py:286` |

- The success write sits inside `_run_directive`, which the L3 planner's dispatch also calls
  (`agent/agent.py:1648`), so live bots do keep writing mine/craft memories.
- Removal: `@bot forget: <query>` recalls the top 3 personal memories and deletes those scoring
  above 0.7 (`agent/agent.py:798-812`). Deletion is scoped to the bot's own rows
  (`agent/semantic_memory.py:233-239`), so the shared copy of a remembered fact survives a forget.
  The dashboard can delete one memory by id (`agent/dashboard/server.py:250-256`).
- Whether the seeding script has been run against the live database: **(no public source)**.
- How many memories the live bots hold: **(no public source)**.

## 4. The hot cache (L1)

- Size: 200 entries per bot (`CACHE_MAX = 200`, `agent/semantic_memory.py:25`).
- What it is: a Python list of `(id, content, category, embedding, metadata, last_accessed)`
  per bot process (`agent/semantic_memory.py:37`). Keyed on nothing: it is scanned linearly,
  comparing the query vector to every entry (`agent/semantic_memory.py:145-155`).
- Warm-up: on connect it loads the bot's 200 most recently accessed rows
  (`agent/semantic_memory.py:50-70`).
- Insertion: new memories and memories pulled up from the database go to the front
  (`agent/semantic_memory.py:126-129`, `391-402`).
- Eviction: when it grows past 200 the **last** entry is dropped (`agent/semantic_memory.py:128-129`,
  `401-402`). A hit does not move an entry to the front, so this is "oldest inserted goes first",
  not true least-recently-used. (The spec and the internal doc say LRU; see section 7.)
- The shared pool is never cached: shared writes skip the cache and shared reads always go to
  the database (`agent/semantic_memory.py:243-311`).

## 5. The vector store (L2)

- Table: `memories` in PostgreSQL with pgvector (`agent/semantic_memory.py:53-59`, `118-121`).
- Columns the code reads or writes: `id, bot_name, category, content, embedding, metadata (jsonb),
  created_at, last_accessed, access_count` (`agent/semantic_memory.py:54`, `119-120`, `346-347`, `385`).
- The table's `CREATE TABLE` and any vector index are **not in the public repo**; index type
  (none, IVFFlat, HNSW): **(no public source)**.
- Embedding model: `nomic-embed-text` served by Ollama's `/api/embeddings`
  (`agent/semantic_memory.py:24`, `72-83`).
- Dimension 768: stated in the spec (`openspec/specs/bot-memory/spec.md:27`, `93`); no constant in the
  code fixes it. Fine to say "768-dimensional, per the spec".
- Similarity: cosine. In the database, pgvector's cosine-distance operator `<=>`, with
  similarity = 1 − distance (`agent/semantic_memory.py:104`, `171-176`); in the cache, numpy
  cosine (`agent/semantic_memory.py:405-410`).
- Personal memories are rows with the bot's own name in `bot_name`; the shared pool is rows
  with `bot_name = 'shared'` (`agent/semantic_memory.py:56`, `243-266`).

## 6. Recall, dedup, and the shared pool

### 6.1 How a query becomes memories (diagram (a))

1. The query text is embedded with the same model (`agent/semantic_memory.py:139`).
2. Cache pass: score every cached entry as cosine × freshness, where freshness = 0.995 ^ (days
   since last access) (`DECAY_RATE = 0.995`, `agent/semantic_memory.py:28`, `145-155`). Unused
   for 30 days, a memory keeps about 86% of its score.
3. Shortcut: if the cache alone gives a full top-k and every one scores above 0.5, stop there
   (`agent/semantic_memory.py:160-164`).
4. Otherwise ask pgvector for the nearest 3 × k rows (`agent/semantic_memory.py:166-190`), apply
   the same freshness factor, merge with the cache results by id, sort, keep top k
   (`agent/semantic_memory.py:192-214`).
5. Every returned memory gets `last_accessed = NOW()` and `access_count + 1`, and database hits are
   pulled into the cache (`agent/semantic_memory.py:216-218`, `380-389`). So using a memory keeps it
   fresh.
6. For a prompt, results become lines like `- [location] Mined 12x iron_ore near (...) (relevance: 81%)`
   (`agent/semantic_memory.py:222-231`).

- Default k is 10 (`RECALL_LIMIT`, `agent/semantic_memory.py:27`); the planner call sites ask for 6
  (`agent/agent.py:997`, `2321`). There is no minimum-similarity cut-off on recall: the top k
  are returned whatever they score.

### 6.2 Dedup rule (diagram (b))

- Before inserting, the new text is embedded and compared with the bot's own memories: first
  the cache (first entry above threshold), then the single nearest row in the database
  (`agent/semantic_memory.py:90-113`).
- Threshold: cosine strictly above 0.85 (`SIMILARITY_THRESHOLD`, `agent/semantic_memory.py:26`,
  `97`, `111`).
- On a match nothing is merged and the text is not updated: the old memory is kept, its access
  time and count are bumped, and the new text is dropped (`agent/semantic_memory.py:98-99`, `112-113`,
  `380-389`).
- Shared writes de-duplicate against the shared pool only, same threshold
  (`agent/semantic_memory.py:249-260`).

### 6.3 The shared pool (diagram (c))

- What goes in: what players tell a bot with `remember:` (tagged with who said it), and the
  one-off crafting seeder (section 3). Bots do **not** add their own discoveries: there is a
  helper that would share location and knowledge finds (`agent/agent.py:2387-2398`), but nothing
  calls it (its definition is its only occurrence in the repo at `6d990e7`).
- How one bot uses it: `recall_all_for_prompt` runs a personal recall and a shared recall, merges
  them by score and marks shared lines `[shared]` (`agent/semantic_memory.py:313-333`). The only
  caller is the task-board path, when a bot claims a task that has no pre-made steps
  (`agent/agent.py:2317-2327`).
- So what is shared is "what a player told one bot, every bot can be reminded of", not "what one
  bot found, another bot uses".

### 6.4 Plan memory (the memory that steers live planning)

- After a plan finishes `complete`, it is recorded (`agent/plan_orchestrator.py:483-485`).
- Before planning a new task, the orchestrator looks for a recorded plan for the same task
  (`agent/plan_orchestrator.py:243-245`). A hit means **zero LLM planning calls**: the old
  steps run again.
- "Same task" means exact text after masking numbers, so "mine 24 oak logs" reuses the plan
  for "mine 12 oak logs" with the count swapped (`agent/plan_memory.py:3-15`, `41`, `48`, `107-112`).
- Only replayed when every step was a skill (deterministic, self-checking) and the plan has no
  absolute coordinates (`agent/plan_memory.py:11-17`, `42`, `57-75`). Index is per bot, built from up
  to 300 archived plans (`agent/plan_memory.py:19`, `39`). On by default (`agent/plan_memory.py:38`).

## 7. What the internal doc (and the 11-11 note) claim that the code does not do

The internal architecture doc is not public; don't link or quote it. The public spec
`openspec/specs/bot-memory/spec.md` repeats most of its claims, so these are also places the
spec is ahead of the code.

| Claim | Code at `6d990e7` |
|---|---|
| L1 uses LRU eviction (spec `:10`) | Oldest-inserted is dropped; hits don't reorder (section 4) |
| A near-duplicate "updates" the existing memory / is "merged" (spec `:53-58`) | Existing memory is kept as is, new text discarded, access time bumped (section 6.2) |
| `decay_score` is a stored field (spec `:30`) | Computed when read, never stored (`agent/semantic_memory.py:357-360`) |
| Shared pool "so bots learn from each other" (spec `:60-66`) | Bots never write to it; the auto-share helper has no caller (section 6.3) |
| The planner calls `recall_for_prompt(instruction, limit=6)` (spec `:68-74`) | True only for the older planner. The live planner (L3) never receives recalled memories (below) |
| The system prompt includes long-term memories | The parameter exists (`agent/prompts.py:146`, `158`) but no caller passes it (`agent/agent.py:622`, `795`; `agent/dashboard/server.py:278`) |
| `semantic_memory.py` is 399 lines | 423 |

**The L3 gap.** On a chat order the bot recalls 6 memories (`agent/agent.py:994-997`), then, when
the bot is on the L3 path, hands the order to the plan orchestrator without them
(`agent/agent.py:1231-1251`, and the earlier branch at `1007-1043`). L3 conversation turns pass an
empty memory string (`agent/agent.py:1983-1988`, `6100-6103`), and the plan orchestrator does no
recall of its own. A bot is on the L3 path when `USE_L3_PLAN_LAYER` is set or the bot is named in
`SCRIPT_BOTS` (`agent/planner.py:306-320`; default off, `agent/config.py:172`). The deployed bots
are all on the L3 path (deployment config, **no public source**). So today the live bots write
vector memories but their planner doesn't read them; plan memory (section 6.4) and the
notebook in the system prompt are what carry experience forward.

## 8. Suggested framing (writer's call, but keep it true)

- Tell it as "a bot remembers two kinds of thing": *what it was told and what it saw* (vector
  memory, with the cache-then-database recall and the dedup rule) and *how it did a job last
  time* (plan memory, which skips the LLM entirely on a repeat task).
- Don't say the bots learn from each other's discoveries, and don't say recalled memories shape
  every plan. "The memory layer recalls the six most relevant memories for the older planner and
  the task board" is true.
- If the post wants the full loop (L3 reading memories), that is a feature to build first, not a
  sentence to write.

## 9. Diagrams

- (a) Recall: query -> embed -> cache scan (cosine × 0.995^days) -> "6 good hits above 0.5?" ->
  yes: return / no: pgvector nearest 3k -> same freshness -> merge by id -> top k -> bump access,
  promote to cache.
- (b) Store: text -> embed -> nearest in cache, then nearest in DB -> above 0.85? -> yes: keep old,
  bump access / no: insert, put at front of cache, drop the last if over 200.
- (c) Who writes and reads the shared pool: players' `remember:` and the seeder write; the task
  board reads; bots' own finds go to their personal store only.

## MUST NOT SAY

No hosts, IPs, cluster or namespace names, bot names or player names. The spec's scenarios use
bot names; don't copy them.
