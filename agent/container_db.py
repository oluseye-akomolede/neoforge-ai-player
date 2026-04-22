"""
Container registry persistence — syncs bot-placed containers between mod and Postgres.

The mod-side ContainerRegistry is an in-memory ConcurrentHashMap.
This module persists to Postgres so data survives restarts, and syncs
the mod's registry on startup from the durable store.
"""

import threading
import psycopg2
import psycopg2.extras
import api


SCHEMA = """
CREATE TABLE IF NOT EXISTS container_registry (
    id SERIAL PRIMARY KEY,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    z INTEGER NOT NULL,
    dimension TEXT NOT NULL DEFAULT 'minecraft:overworld',
    placed_by TEXT NOT NULL DEFAULT 'unknown',
    created_at BIGINT DEFAULT 0,
    removed BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_container_dim ON container_registry(dimension) WHERE NOT removed;
"""


class ContainerDB:
    def __init__(self, pg_dsn):
        self.pg_dsn = pg_dsn
        self._conn = None
        self._lock = threading.Lock()
        self._cache = {}  # id -> {x, y, z, dimension, placed_by}

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
                    cur.execute("SELECT id, x, y, z, dimension, placed_by FROM container_registry WHERE NOT removed")
                    self._cache = {}
                    for row in cur.fetchall():
                        self._cache[row["id"]] = {
                            "x": row["x"], "y": row["y"], "z": row["z"],
                            "dimension": row["dimension"], "placed_by": row["placed_by"],
                        }
            except Exception as e:
                print(f"[container_db] cache load error: {e}")

    def register(self, x, y, z, dimension, placed_by):
        """Insert a new container and return its ID."""
        with self._lock:
            try:
                self._ensure_conn()
                with self._conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO container_registry (x, y, z, dimension, placed_by, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, EXTRACT(EPOCH FROM NOW())::BIGINT) RETURNING id",
                        (x, y, z, dimension, placed_by),
                    )
                    cid = cur.fetchone()[0]
                    self._cache[cid] = {
                        "x": x, "y": y, "z": z,
                        "dimension": dimension, "placed_by": placed_by,
                    }
                    return cid
            except Exception as e:
                print(f"[container_db] register error: {e}")
                return -1

    def remove(self, container_id):
        """Soft-delete a container (destroyed in world)."""
        with self._lock:
            try:
                self._ensure_conn()
                with self._conn.cursor() as cur:
                    cur.execute(
                        "UPDATE container_registry SET removed = TRUE WHERE id = %s",
                        (container_id,),
                    )
                self._cache.pop(container_id, None)
            except Exception as e:
                print(f"[container_db] remove error: {e}")

    def get_all(self):
        """Return all active containers."""
        with self._lock:
            return dict(self._cache)

    def sync_to_mod(self):
        """Push all known containers to the mod's in-memory registry."""
        containers = self.get_all()
        for cid, info in containers.items():
            try:
                api.raw_post("/containers", {
                    "id": cid,
                    "x": info["x"], "y": info["y"], "z": info["z"],
                    "dimension": info["dimension"],
                    "placed_by": info["placed_by"],
                })
            except Exception as e:
                print(f"[container_db] sync_to_mod error for #{cid}: {e}")
        count = len(containers)
        if count > 0:
            print(f"[container_db] Synced {count} containers to mod")

    def sync_from_mod(self):
        """Pull containers from mod and merge into Postgres."""
        try:
            data = api.raw_get("/containers")
            mod_containers = data.get("containers", [])
        except Exception as e:
            print(f"[container_db] sync_from_mod error: {e}")
            return

        with self._lock:
            try:
                self._ensure_conn()
                for c in mod_containers:
                    cid = c.get("id")
                    if cid and cid not in self._cache:
                        with self._conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO container_registry (id, x, y, z, dimension, placed_by, created_at) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                                (cid, c["x"], c["y"], c["z"],
                                 c.get("dimension", "minecraft:overworld"),
                                 c.get("placed_by", "unknown"),
                                 c.get("created_at", 0)),
                            )
                        self._cache[cid] = {
                            "x": c["x"], "y": c["y"], "z": c["z"],
                            "dimension": c.get("dimension", "minecraft:overworld"),
                            "placed_by": c.get("placed_by", "unknown"),
                        }
            except Exception as e:
                print(f"[container_db] sync_from_mod merge error: {e}")

    def summary_for_prompt(self):
        """Short text summary for LLM context."""
        containers = self.get_all()
        if not containers:
            return ""
        lines = []
        for cid, info in list(containers.items())[:20]:
            lines.append(f"  #{cid} at ({info['x']}, {info['y']}, {info['z']}) [{info['dimension']}] by {info['placed_by']}")
        return f"{len(containers)} containers:\n" + "\n".join(lines)
