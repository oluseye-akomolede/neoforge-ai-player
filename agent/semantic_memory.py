"""
Hierarchical semantic memory system for AI bots.

Architecture:
  L1: In-memory vector cache (hot memories, fast cosine similarity)
  L2: pgvector database (cold storage, full semantic search)

Memories are categorized:
  - location: where things are (barrels, farms, builds, landmarks)
  - instruction: standing orders from players
  - knowledge: world state, resource info, crafting notes
  - event: significant things that happened
"""

import json
import time
import threading
import numpy as np
import requests
import psycopg2
import psycopg2.extras


EMBED_MODEL = "nomic-embed-text"
CACHE_MAX = 200
SIMILARITY_THRESHOLD = 0.85
RECALL_LIMIT = 10


class SemanticMemory:
    def __init__(self, bot_name, ollama_url, pg_dsn):
        self.bot_name = bot_name
        self.ollama_url = ollama_url
        self.pg_dsn = pg_dsn
        self._cache = []  # list of (id, content, category, embedding, metadata)
        self._lock = threading.Lock()
        self._conn = None

    def connect(self):
        self._conn = psycopg2.connect(self.pg_dsn)
        self._conn.autocommit = True
        self._warm_cache()

    def close(self):
        if self._conn:
            self._conn.close()

    def _warm_cache(self):
        """Load most recently accessed memories into L1 cache."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, content, category, embedding, metadata
                FROM memories
                WHERE bot_name = %s
                ORDER BY last_accessed DESC
                LIMIT %s
            """, (self.bot_name, CACHE_MAX))
            rows = cur.fetchall()
            with self._lock:
                self._cache = []
                for row in rows:
                    emb = _pg_vector_to_numpy(row["embedding"]) if row["embedding"] else None
                    meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
                    self._cache.append((
                        row["id"], row["content"], row["category"], emb, meta
                    ))

    def _embed(self, text):
        """Generate embedding via ollama."""
        resp = requests.post(
            f"{self.ollama_url}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=10,
        )
        resp.raise_for_status()
        vec = resp.json()["embedding"]
        return np.array(vec, dtype=np.float32)

    def store(self, content, category="knowledge", metadata=None):
        """Store a new memory. Deduplicates against existing memories."""
        if not content or not content.strip():
            return None

        embedding = self._embed(content)

        # Check for duplicate in cache first
        with self._lock:
            for mid, mcontent, mcat, memb, mmeta in self._cache:
                if memb is not None:
                    sim = _cosine_sim(embedding, memb)
                    if sim > SIMILARITY_THRESHOLD:
                        self._update_access(mid)
                        return mid

        # Check DB for duplicate
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT id, 1 - (embedding <=> %s::vector) as similarity
                FROM memories
                WHERE bot_name = %s AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 1
            """, (_numpy_to_pg(embedding), self.bot_name, _numpy_to_pg(embedding)))
            row = cur.fetchone()
            if row and row[1] > SIMILARITY_THRESHOLD:
                self._update_access(row[0])
                return row[0]

        # Insert new memory
        meta = json.dumps(metadata or {})
        with self._conn.cursor() as cur:
            cur.execute("""
                INSERT INTO memories (bot_name, category, content, embedding, metadata)
                VALUES (%s, %s, %s, %s::vector, %s::jsonb)
                RETURNING id
            """, (self.bot_name, category, content.strip(), _numpy_to_pg(embedding), meta))
            new_id = cur.fetchone()[0]

        # Add to L1 cache
        with self._lock:
            self._cache.insert(0, (new_id, content.strip(), category, embedding, metadata or {}))
            if len(self._cache) > CACHE_MAX:
                self._cache.pop()

        return new_id

    def recall(self, query, category=None, limit=None):
        """Retrieve memories semantically similar to the query.

        Returns list of dicts: {id, content, category, similarity, metadata}
        """
        limit = limit or RECALL_LIMIT
        query_emb = self._embed(query)

        # L1: check cache first
        results = []
        with self._lock:
            for mid, content, cat, emb, meta in self._cache:
                if category and cat != category:
                    continue
                if emb is not None:
                    sim = _cosine_sim(query_emb, emb)
                    results.append({
                        "id": mid, "content": content, "category": cat,
                        "similarity": float(sim), "metadata": meta, "source": "cache",
                    })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        cache_results = results[:limit]

        # If cache has enough high-quality results, skip DB
        if len(cache_results) >= limit and all(r["similarity"] > 0.5 for r in cache_results):
            for r in cache_results:
                self._update_access(r["id"])
            return cache_results

        # L2: query pgvector
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if category:
                cur.execute("""
                    SELECT id, content, category, metadata,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM memories
                    WHERE bot_name = %s AND category = %s AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (_numpy_to_pg(query_emb), self.bot_name, category,
                      _numpy_to_pg(query_emb), limit))
            else:
                cur.execute("""
                    SELECT id, content, category, metadata,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM memories
                    WHERE bot_name = %s AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (_numpy_to_pg(query_emb), self.bot_name,
                      _numpy_to_pg(query_emb), limit))

            db_rows = cur.fetchall()

        # Merge cache + DB results, deduplicate by id
        seen_ids = set()
        merged = []
        for r in cache_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                merged.append(r)
        for row in db_rows:
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
                merged.append({
                    "id": row["id"], "content": row["content"],
                    "category": row["category"], "similarity": float(row["similarity"]),
                    "metadata": meta, "source": "db",
                })

        merged.sort(key=lambda x: x["similarity"], reverse=True)
        final = merged[:limit]

        for r in final:
            self._update_access(r["id"])
            self._promote_to_cache(r)

        return final

    def recall_for_prompt(self, query, limit=8):
        """Recall memories formatted for inclusion in the LLM prompt."""
        memories = self.recall(query, limit=limit)
        if not memories:
            return "No relevant memories."
        lines = []
        for m in memories:
            sim_pct = int(m["similarity"] * 100)
            lines.append(f"- [{m['category']}] {m['content']} (relevance: {sim_pct}%)")
        return "\n".join(lines)

    def forget(self, memory_id):
        """Delete a memory by ID."""
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM memories WHERE id = %s AND bot_name = %s", (memory_id, self.bot_name))
        with self._lock:
            self._cache = [e for e in self._cache if e[0] != memory_id]

    def list_by_category(self, category, limit=20):
        """List memories in a category."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, content, category, metadata, created_at
                FROM memories
                WHERE bot_name = %s AND category = %s
                ORDER BY last_accessed DESC
                LIMIT %s
            """, (self.bot_name, category, limit))
            return [dict(row) for row in cur.fetchall()]

    def stats(self):
        """Return memory stats for this bot."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT category, COUNT(*) as count
                FROM memories WHERE bot_name = %s
                GROUP BY category ORDER BY count DESC
            """, (self.bot_name,))
            categories = {row["category"]: row["count"] for row in cur.fetchall()}
        return {
            "bot": self.bot_name,
            "total": sum(categories.values()),
            "cached": len(self._cache),
            "categories": categories,
        }

    def _update_access(self, memory_id):
        """Update access timestamp and counter."""
        try:
            with self._conn.cursor() as cur:
                cur.execute("""
                    UPDATE memories SET last_accessed = NOW(), access_count = access_count + 1
                    WHERE id = %s
                """, (memory_id,))
        except Exception:
            pass

    def _promote_to_cache(self, result):
        """Promote a DB result to L1 cache if not already present."""
        with self._lock:
            if any(e[0] == result["id"] for e in self._cache):
                return
            emb = self._embed(result["content"])
            self._cache.insert(0, (
                result["id"], result["content"], result["category"],
                emb, result.get("metadata", {})
            ))
            if len(self._cache) > CACHE_MAX:
                self._cache.pop()


def _cosine_sim(a, b):
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return dot / norm


def _numpy_to_pg(arr):
    return "[" + ",".join(str(float(x)) for x in arr) + "]"


def _pg_vector_to_numpy(pg_str):
    if pg_str is None:
        return None
    if isinstance(pg_str, str):
        clean = pg_str.strip("[]")
        return np.array([float(x) for x in clean.split(",")], dtype=np.float32)
    return np.array(pg_str, dtype=np.float32)
