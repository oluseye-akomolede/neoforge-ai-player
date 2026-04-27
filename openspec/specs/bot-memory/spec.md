# Bot Memory Specification

## Purpose
Defines the semantic memory system — how bots store, retrieve, and share learned knowledge using vector embeddings.

## Requirements

### Requirement: Two-Tier Memory Architecture
Each bot MUST have a two-tier memory system:
- L1 Cache: In-memory numpy vectors (max 200 hot memories, LRU eviction)
- L2 Store: PostgreSQL with pgvector extension (full history, semantic search)

#### Scenario: Memory retrieval with cache promotion
- GIVEN a bot recalls "diamond location" from L2
- WHEN the memory is accessed
- THEN it is promoted to L1 cache for faster future retrieval

### Requirement: Memory Entry Structure
Each memory entry MUST contain:

| Field | Type | Description |
|-------|------|-------------|
| id | int | Unique identifier (auto-increment) |
| bot_name | string | Owning bot (or "shared" for shared pool) |
| category | enum | location, instruction, knowledge, event |
| content | string | Natural language memory content |
| embedding | vector(768) | nomic-embed-text embedding |
| created_at | timestamp | Creation time |
| access_count | int | Number of times recalled |
| decay_score | float | Freshness score (0.0-1.0) |

#### Scenario: Stored memory contains all required fields
- GIVEN a bot stores a new memory "Found diamonds at Y=12"
- WHEN the memory is persisted to the L2 store
- THEN the entry contains all required fields including id, bot_name, category, content, embedding, created_at, access_count, and decay_score

### Requirement: Memory Categories
Memories MUST be classified into exactly one of four categories:

| Category | Description | Example |
|----------|-------------|---------|
| location | Spatial knowledge | "Found diamonds below Y=16 near (1000, 50, 500)" |
| instruction | Player directives | "Player said to always mine iron before gold" |
| knowledge | Learned facts | "Oak trees grow fastest in plains biome" |
| event | Action outcomes | "Stored 64x cobblestone in container #3" |

#### Scenario: Memory is classified into exactly one category
- GIVEN a bot stores the memory "Player said to always mine iron before gold"
- WHEN the memory is classified
- THEN it is assigned the category "instruction" and no other category

### Requirement: Deduplication
Before inserting a new memory, the system MUST check existing vectors for cosine similarity > 85%. If a match is found, the existing memory MUST be updated rather than creating a duplicate.

#### Scenario: Duplicate memory prevention
- GIVEN a bot stores "Found iron at Y=30 near spawn"
- WHEN it later tries to store "Iron deposits at Y=30 close to spawn"
- THEN the original memory is updated (not duplicated)

### Requirement: Shared Memory Pool
A shared memory pool (bot_name="shared") MUST be readable by all bots for cross-bot knowledge sharing.

#### Scenario: Cross-bot knowledge
- GIVEN Scout stores a shared memory "Nether fortress at (100, 70, -200)"
- WHEN Mystic recalls memories for "nether fortress"
- THEN Scout's shared memory is included in results

### Requirement: Memory Recall for Planning
When the LLM planner decomposes a task, it MUST call `recall_for_prompt(instruction, limit=6)` to inject relevant memories as context.

#### Scenario: Relevant memories injected into planner context
- GIVEN a bot has stored memories about diamond locations
- WHEN the LLM planner decomposes the task "mine diamonds"
- THEN recall_for_prompt is called with the instruction and up to 6 relevant memories are included in the planner context

### Requirement: Memory Management
Users MUST be able to:
- Store memories via in-game chat (`@bot remember: <content>`)
- Delete memories via in-game chat (`@bot forget: <query>`)
- Delete individual memories via dashboard API (`DELETE /api/bots/{name}/memories/{id}`)

#### Scenario: Store memory via in-game chat
- GIVEN a player is in-game with a bot named Scout
- WHEN the player types "@Scout remember: base is at 100 64 200"
- THEN a new memory is stored for Scout with the content "base is at 100 64 200"

#### Scenario: Delete memory via in-game chat
- GIVEN Scout has a stored memory about the base location
- WHEN the player types "@Scout forget: base location"
- THEN the matching memory is deleted from Scout's memory store

### Requirement: Embedding Model
All embeddings MUST use `nomic-embed-text` via Ollama, producing 768-dimensional vectors with cosine similarity for retrieval.

#### Scenario: Embedding dimensions match expected size
- GIVEN a bot stores a new memory with content "Iron found near river"
- WHEN the embedding is generated via Ollama
- THEN the resulting vector has exactly 768 dimensions

### Requirement: Memory Serialization
A bot's complete memory state MUST be exportable as a list of memory entries with all fields from the Memory Entry Structure requirement.

#### Scenario: Export bot memory state
- GIVEN a bot named Scout has 5 stored memories
- WHEN the memory state is exported
- THEN the result is a list of 5 memory entries each containing all fields defined in the Memory Entry Structure requirement
