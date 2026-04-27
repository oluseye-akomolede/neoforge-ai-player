"""
Terrain persistence — stores surface scan data from bots into Postgres.

Bots passively scan a 25x25 area around them every ~30 seconds.
The dashboard reads this to render a world map overlay.
"""

import threading
import psycopg2
import psycopg2.extras

SCHEMA = """
CREATE TABLE IF NOT EXISTS terrain_blocks (
    x INTEGER NOT NULL,
    z INTEGER NOT NULL,
    y INTEGER NOT NULL,
    dimension TEXT NOT NULL,
    block TEXT NOT NULL,
    scanned_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (x, z, dimension)
);
CREATE INDEX IF NOT EXISTS idx_terrain_dim ON terrain_blocks(dimension);
"""


class TerrainDB:
    def __init__(self, pg_dsn):
        self.pg_dsn = pg_dsn
        self._conn = None
        self._lock = threading.Lock()

    def connect(self):
        self._conn = psycopg2.connect(self.pg_dsn)
        self._conn.autocommit = True
        with self._conn.cursor() as cur:
            cur.execute(SCHEMA)

    def _ensure_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.pg_dsn)
            self._conn.autocommit = True

    def store_scan(self, blocks, dimension):
        if not blocks:
            return 0
        with self._lock:
            self._ensure_conn()
            with self._conn.cursor() as cur:
                args = [(b["x"], b["z"], b["y"], dimension, b["block"]) for b in blocks]
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO terrain_blocks (x, z, y, dimension, block)
                       VALUES %s
                       ON CONFLICT (x, z, dimension)
                       DO UPDATE SET y = EXCLUDED.y, block = EXCLUDED.block, scanned_at = NOW()""",
                    args,
                    page_size=500,
                )
            return len(blocks)

    def get_region(self, dimension, x_min, x_max, z_min, z_max, limit=10000):
        with self._lock:
            self._ensure_conn()
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT x, z, y, block FROM terrain_blocks
                       WHERE dimension = %s AND x BETWEEN %s AND %s AND z BETWEEN %s AND %s
                       ORDER BY x, z LIMIT %s""",
                    (dimension, x_min, x_max, z_min, z_max, limit),
                )
                return [dict(row) for row in cur.fetchall()]

    def get_around(self, dimension, cx, cz, radius=50, limit=10000):
        return self.get_region(
            dimension, cx - radius, cx + radius, cz - radius, cz + radius, limit
        )

    def stats(self):
        with self._lock:
            self._ensure_conn()
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT dimension, COUNT(*) as count FROM terrain_blocks GROUP BY dimension"
                )
                return {row["dimension"]: row["count"] for row in cur.fetchall()}

    def close(self):
        if self._conn:
            self._conn.close()
