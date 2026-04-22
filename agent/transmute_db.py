"""
Transmute registry persistence — syncs discovered items from the mod API to Postgres.

The mod-side TransmuteRegistry discovers items at L1 (tick-safe Java ConcurrentHashMap).
This module periodically pulls the registry via HTTP and upserts into Postgres so:
  1. Data survives server restarts (Postgres is the durable store)
  2. The agent/LLM can query known transmutable items for conjure planning
  3. Items discovered by any bot are globally visible
"""

import threading
import time
import psycopg2
import psycopg2.extras
import api


SCHEMA = """
CREATE TABLE IF NOT EXISTS transmute_registry (
    item_id TEXT PRIMARY KEY,
    xp_cost INTEGER NOT NULL,
    source TEXT DEFAULT 'unknown',
    discovered_tick BIGINT DEFAULT 0,
    synced_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_transmute_cost ON transmute_registry(xp_cost);
"""


class TransmuteDB:
    def __init__(self, pg_dsn):
        self.pg_dsn = pg_dsn
        self._conn = None
        self._lock = threading.Lock()
        self._cache = {}  # item_id -> xp_cost
        self._last_sync = 0

    def connect(self):
        self._conn = psycopg2.connect(self.pg_dsn)
        self._conn.autocommit = True
        with self._conn.cursor() as cur:
            cur.execute(SCHEMA)
        self._load_cache()

    def _ensure_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.pg_dsn)
            self._conn.autocommit = True

    def _load_cache(self):
        with self._lock:
            try:
                self._ensure_conn()
                with self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("SELECT item_id, xp_cost FROM transmute_registry")
                    self._cache = {row["item_id"]: row["xp_cost"] for row in cur.fetchall()}
            except Exception as e:
                print(f"[transmute_db] cache load error: {e}")

    def sync_from_mod(self):
        """Pull the mod's transmute registry and upsert into Postgres."""
        try:
            resp = api.transmute_list()
            items = resp.get("items", [])
            if not items:
                return 0

            self._ensure_conn()
            new_count = 0
            with self._conn.cursor() as cur:
                for item in items:
                    item_id = item["item"]
                    xp_cost = item["xp_cost"]
                    source = item.get("source", "mod")
                    tick = item.get("discovered_tick", 0)

                    cur.execute("""
                        INSERT INTO transmute_registry (item_id, xp_cost, source, discovered_tick, synced_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (item_id) DO UPDATE SET
                            xp_cost = EXCLUDED.xp_cost,
                            source = EXCLUDED.source,
                            synced_at = NOW()
                    """, (item_id, xp_cost, source, tick))
                    if item_id not in self._cache:
                        new_count += 1
                    self._cache[item_id] = xp_cost

            self._last_sync = time.time()
            if new_count > 0:
                print(f"[transmute_db] synced {len(items)} items ({new_count} new)")
            return new_count
        except Exception as e:
            print(f"[transmute_db] sync error: {e}")
            return 0

    def get_cost(self, item_id):
        return self._cache.get(item_id)

    def is_known(self, item_id):
        return item_id in self._cache

    def get_all(self):
        return dict(self._cache)

    def get_conjurable_items(self):
        """Return list of item IDs and costs for LLM context."""
        return sorted(self._cache.items(), key=lambda x: x[1])

    def get_context_string(self, max_items=50):
        """Build a compact string for LLM prompts listing known transmutable items."""
        items = self.get_conjurable_items()
        if not items:
            return "No discovered transmutable items yet."
        lines = [f"Known transmutable items ({len(items)} total):"]
        for item_id, cost in items[:max_items]:
            lines.append(f"  {item_id}: {cost} XP")
        if len(items) > max_items:
            lines.append(f"  ... and {len(items) - max_items} more")
        return "\n".join(lines)
