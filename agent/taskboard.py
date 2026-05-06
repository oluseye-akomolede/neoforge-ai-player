"""
Shared task board — centralized task queue for multi-bot coordination.

Tasks flow:
  Player instruction → Orchestrator decomposes → posts sub-tasks to board
  → bots claim tasks matching their specialization → execute → report done

Architecture:
  L1: In-memory cache of active tasks (fast reads, checked every tick)
  L2: Postgres table (source of truth, used for writes and cache refresh)

The cache avoids a postgres round-trip on every idle tick. Writes always
go through postgres first, then refresh the cache. Claims use postgres
FOR UPDATE SKIP LOCKED for atomic multi-bot safety.
"""

import json
import time
import threading
import psycopg2
import psycopg2.extras


SCHEMA = """
CREATE TABLE IF NOT EXISTS task_board (
    id SERIAL PRIMARY KEY,
    description TEXT NOT NULL,
    parent_id INTEGER REFERENCES task_board(id),
    specialization TEXT,
    status TEXT DEFAULT 'pending',
    assigned_to TEXT,
    created_by TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    result TEXT,
    plan_steps JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_status ON task_board(status);
CREATE INDEX IF NOT EXISTS idx_task_assigned ON task_board(assigned_to);
"""

ACTIVE_STATUSES = ('pending', 'assigned', 'in_progress')


class TaskBoard:
    def __init__(self, pg_dsn):
        self.pg_dsn = pg_dsn
        self._conn = None
        self._lock = threading.Lock()
        self._cache = []  # list of task dicts (active tasks only)
        self._cache_ts = 0  # last refresh timestamp

    def connect(self):
        self._conn = psycopg2.connect(self.pg_dsn)
        self._conn.autocommit = True
        with self._conn.cursor() as cur:
            cur.execute(SCHEMA)
        self._refresh_cache()

    def close(self):
        if self._conn:
            self._conn.close()

    # ── Cache management ──

    def _refresh_cache(self):
        """Reload active tasks from postgres into the L1 cache."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM task_board
                WHERE status IN %s
                ORDER BY priority DESC, created_at ASC
                LIMIT 100
            """, (ACTIVE_STATUSES,))
            rows = cur.fetchall()
        with self._lock:
            self._cache = [dict(r) for r in rows]
            self._cache_ts = time.time()

    def _cache_has_claimable(self, bot_name, specializations=None):
        """Fast check: tasks pre-assigned to this bot, or pending tasks matching specs."""
        with self._lock:
            for t in self._cache:
                if t["status"] == "assigned" and t.get("assigned_to") == bot_name:
                    return True
                if t["status"] != "pending":
                    continue
                if specializations:
                    spec = t.get("specialization")
                    if spec is not None and spec not in specializations:
                        continue
                return True
        return False

    def _remove_from_cache(self, task_id):
        """Remove a task from cache (after done/failed)."""
        with self._lock:
            self._cache = [t for t in self._cache if t["id"] != task_id]

    def _update_cache_entry(self, task_id, **fields):
        """Update fields of a cached task in-place."""
        with self._lock:
            for t in self._cache:
                if t["id"] == task_id:
                    t.update(fields)
                    return

    # ── Public API ──

    def post(self, description, created_by, specialization=None, priority=0,
             parent_id=None, plan_steps=None, assigned_to=None):
        """Post a new task to the board. Returns task id.
        If assigned_to is set, task is pre-assigned (status='assigned') so only that bot picks it up."""
        status = "assigned" if assigned_to else "pending"
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO task_board
                    (description, created_by, specialization, priority, parent_id, plan_steps,
                     status, assigned_to)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                RETURNING *
            """, (description, created_by, specialization, priority,
                  parent_id, json.dumps(plan_steps) if plan_steps else None,
                  status, assigned_to))
            row = dict(cur.fetchone())
        with self._lock:
            self._cache.append(row)
        return row["id"]

    def claim(self, bot_name, specializations=None):
        """Claim a task: pre-assigned to this bot first, then highest-priority pending.

        Fast path: check cache first. If nothing claimable, skip postgres entirely.
        Slow path: atomic claim via postgres FOR UPDATE SKIP LOCKED.
        Returns task dict or None.
        """
        if not self._cache_has_claimable(bot_name, specializations):
            return None

        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # First: pick up tasks pre-assigned to this bot
            cur.execute("""
                UPDATE task_board
                SET status = 'assigned', updated_at = NOW()
                WHERE id = (
                    SELECT id FROM task_board
                    WHERE status = 'assigned' AND assigned_to = %s
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
            """, (bot_name,))
            row = cur.fetchone()

            # Then: fall back to pending tasks
            if not row:
                if specializations:
                    placeholders = ",".join(["%s"] * len(specializations))
                    cur.execute(f"""
                        UPDATE task_board
                        SET status = 'assigned', assigned_to = %s, updated_at = NOW()
                        WHERE id = (
                            SELECT id FROM task_board
                            WHERE status = 'pending'
                              AND (specialization IS NULL OR specialization IN ({placeholders}))
                            ORDER BY priority DESC, created_at ASC
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING *
                    """, [bot_name] + list(specializations))
                else:
                    cur.execute("""
                        UPDATE task_board
                        SET status = 'assigned', assigned_to = %s, updated_at = NOW()
                        WHERE id = (
                            SELECT id FROM task_board
                            WHERE status = 'pending'
                              AND specialization IS NULL
                            ORDER BY priority DESC, created_at ASC
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING *
                    """, (bot_name,))
                row = cur.fetchone()

        if row:
            task = dict(row)
            self._update_cache_entry(task["id"], status="assigned", assigned_to=bot_name)
            return task
        return None

    def start(self, task_id):
        """Mark a task as in_progress."""
        with self._conn.cursor() as cur:
            cur.execute("""
                UPDATE task_board SET status = 'in_progress', updated_at = NOW()
                WHERE id = %s
            """, (task_id,))
        self._update_cache_entry(task_id, status="in_progress")

    def complete(self, task_id, result=""):
        """Mark a task as done."""
        with self._conn.cursor() as cur:
            cur.execute("""
                UPDATE task_board SET status = 'done', result = %s, updated_at = NOW()
                WHERE id = %s
            """, (result, task_id))
        self._remove_from_cache(task_id)

    def fail(self, task_id, reason=""):
        """Mark a task as failed."""
        with self._conn.cursor() as cur:
            cur.execute("""
                UPDATE task_board SET status = 'failed', result = %s, updated_at = NOW()
                WHERE id = %s
            """, (reason, task_id))
        self._remove_from_cache(task_id)

    def release(self, task_id):
        """Release a claimed task back to pending."""
        with self._conn.cursor() as cur:
            cur.execute("""
                UPDATE task_board
                SET status = 'pending', assigned_to = NULL, updated_at = NOW()
                WHERE id = %s
            """, (task_id,))
        self._update_cache_entry(task_id, status="pending", assigned_to=None)

    def clear_all(self):
        """Delete all tasks from the board."""
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM task_board")
        with self._lock:
            self._cache.clear()

    def pending_count(self, specialization=None):
        """Count pending tasks from cache (no postgres hit)."""
        with self._lock:
            count = 0
            for t in self._cache:
                if t["status"] != "pending":
                    continue
                if specialization:
                    spec = t.get("specialization")
                    if spec is not None and spec != specialization:
                        continue
                count += 1
            return count

    def get(self, task_id):
        """Get a task by id. Check cache first, fall back to postgres."""
        with self._lock:
            for t in self._cache:
                if t["id"] == task_id:
                    return dict(t)
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM task_board WHERE id = %s", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_active(self, limit=20):
        """List all active tasks from cache (no postgres hit)."""
        with self._lock:
            return [dict(t) for t in self._cache[:limit]]

    def list_recent(self, limit=50):
        """List all recent tasks from postgres (all statuses)."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM task_board
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]

    def delete_task(self, task_id):
        """Delete a single task by id."""
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM task_board WHERE id = %s", (task_id,))
            deleted = cur.rowcount > 0
        if deleted:
            self._remove_from_cache(task_id)
        return deleted

    def cleanup_stale(self, max_age_seconds=300):
        """Fail tasks that have been assigned/in_progress too long.
        Hits postgres and refreshes cache."""
        with self._conn.cursor() as cur:
            cur.execute("""
                UPDATE task_board
                SET status = 'failed', result = 'Timed out (stale)', updated_at = NOW()
                WHERE status IN ('assigned', 'in_progress')
                  AND updated_at < NOW() - INTERVAL '%s seconds'
            """, (max_age_seconds,))
            count = cur.rowcount
        if count > 0:
            self._refresh_cache()
        return count
