"""
FastAPI dashboard server — REST + WebSocket endpoints.

Runs in a daemon thread alongside the synchronous agent tick loop.
Serves the React SPA from /static and provides /api/* endpoints.
"""

import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .state import shared_state
from .schemas import (
    CommandRequest, DirectiveRequest, BroadcastRequest,
    WaypointRequest, WaypointDeleteRequest, DIRECTIVE_CATALOG,
)


STATIC_DIR = Path(__file__).parent.parent / "static"

_api_module = None
_agent_module = None
_taskboard = None
_transmute = None
_container_db = None
_waypoints_module = None
_terrain_db = None


def _bind_agent_refs(api_mod, agent_mod, tb, tx, cdb, wp, tdb=None):
    global _api_module, _agent_module, _taskboard, _transmute, _container_db, _waypoints_module, _terrain_db
    _api_module = api_mod
    _agent_module = agent_mod
    _taskboard = tb
    _transmute = tx
    _container_db = cdb
    _waypoints_module = wp
    _terrain_db = tdb


def _get_runner(name: str):
    runners = getattr(_agent_module, '_all_runners', {})
    return runners.get(name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    shared_state.bind_loop(asyncio.get_running_loop())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AI Bot Dashboard", lifespan=lifespan)

    # ── WebSocket: live state stream ──

    @app.websocket("/ws")
    async def ws_state(ws: WebSocket):
        await ws.accept()
        last_version = 0
        try:
            while True:
                await shared_state.changed()
                snap = shared_state.snapshot()
                if snap["version"] != last_version:
                    last_version = snap["version"]
                    await ws.send_json(snap)
        except WebSocketDisconnect:
            pass

    # ── WebSocket: event stream ──

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket):
        await ws.accept()
        last_ts = time.time()
        try:
            while True:
                await shared_state.changed()
                events = shared_state.events_since(last_ts)
                if events:
                    last_ts = events[-1]["ts"]
                    await ws.send_json({"events": events})
        except WebSocketDisconnect:
            pass

    # ── REST: snapshot ──

    @app.get("/api/state")
    async def get_state():
        return shared_state.snapshot()

    # ── REST: bot list and details ──

    @app.get("/api/bots")
    async def get_bots():
        snap = shared_state.snapshot()
        return {"bots": list(snap["bots"].keys())}

    @app.get("/api/bots/{name}")
    async def get_bot(name: str):
        snap = shared_state.snapshot()
        bot = snap["bots"].get(name)
        if not bot:
            return {"error": "bot not found"}
        return bot

    # ── REST: bot memories (semantic memory) ──

    @app.get("/api/bots/{name}/memories")
    async def get_bot_memories(name: str, category: str = Query("all"), limit: int = Query(30)):
        runner = _get_runner(name)
        if not runner or not runner.semantic_mem:
            return {"memories": [], "error": "semantic memory unavailable"}
        try:
            if category == "all":
                stats = runner.semantic_mem.stats()
                memories = []
                for cat in stats.get("categories", {}):
                    memories.extend(runner.semantic_mem.list_by_category(cat, limit=limit))
                memories.sort(key=lambda m: str(m.get("created_at", "")), reverse=True)
                return {"memories": memories[:limit], "stats": stats}
            else:
                memories = runner.semantic_mem.list_by_category(category, limit=limit)
                return {"memories": memories}
        except Exception as e:
            return {"memories": [], "error": str(e)}

    @app.delete("/api/bots/{name}/memories/{memory_id}")
    async def delete_bot_memory(name: str, memory_id: int):
        runner = _get_runner(name)
        if not runner or not runner.semantic_mem:
            return {"status": "error", "detail": "semantic memory unavailable"}
        try:
            await asyncio.to_thread(runner.semantic_mem.delete, memory_id)
            return {"status": "deleted", "id": memory_id}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    # ── REST: bot profile (export / import) ──

    @app.get("/api/bots/{name}/profile")
    async def get_bot_profile(name: str):
        runner = _get_runner(name)
        if not runner:
            return {"error": "bot not found"}
        return {"profile": runner.profile}

    @app.post("/api/bots/{name}/profile")
    async def set_bot_profile(name: str, body: dict):
        runner = _get_runner(name)
        if not runner:
            return {"error": "bot not found"}
        profile_data = body.get("profile", body)
        runner.profile = profile_data
        import prompts
        runner.system_prompt = prompts.build_system_prompt(
            runner.profile, runner.memory_entries
        )
        return {"status": "profile_updated", "name": profile_data.get("name", name)}

    # ── REST: bulk memory import ──

    @app.post("/api/bots/{name}/memories/import")
    async def import_bot_memories(name: str, body: dict):
        runner = _get_runner(name)
        if not runner or not runner.semantic_mem:
            return {"status": "error", "detail": "semantic memory unavailable"}
        memories = body.get("memories", [])
        imported = 0
        skipped = 0
        for mem in memories:
            content = mem.get("content", "")
            category = mem.get("category", "knowledge")
            metadata = mem.get("metadata", {})
            if not content:
                skipped += 1
                continue
            try:
                mid = await asyncio.to_thread(
                    runner.semantic_mem.store, content, category=category, metadata=metadata
                )
                if mid is not None:
                    imported += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1
        return {"status": "imported", "imported": imported, "skipped": skipped, "total": len(memories)}

    # ── REST: send chat command (goes through orchestrator) ──

    @app.post("/api/command")
    async def send_command(req: CommandRequest):
        if not _api_module:
            return {"error": "agent not connected"}
        try:
            await asyncio.to_thread(_api_module.system_chat, req.bot, f"[dashboard] {req.message}", "gold")
            await asyncio.to_thread(_api_module.inject_chat, req.bot, "dashboard", req.message)
            shared_state.push_event({
                "type": "command_sent",
                "bot": req.bot,
                "message": req.message[:120],
                "source": "dashboard",
            })
            return {"ok": True, "status": "sent_to_planner"}
        except Exception as e:
            return {"error": str(e)}

    # ── REST: broadcast to all bots ──

    @app.post("/api/broadcast")
    async def broadcast(req: BroadcastRequest):
        if not _api_module:
            return {"error": "agent not connected"}
        snap = shared_state.snapshot()
        results = {}
        for bot_name in snap["bots"]:
            try:
                await asyncio.to_thread(_api_module.chat, bot_name, req.message)
                results[bot_name] = "ok"
            except Exception as e:
                results[bot_name] = str(e)
        return {"results": results}

    # ── REST: fire L1 directive directly ──

    @app.post("/api/directive")
    async def send_directive(req: DirectiveRequest):
        if not _api_module:
            return {"error": "agent not connected"}
        try:
            result = await asyncio.to_thread(
                _api_module.set_directive,
                req.bot, req.directive_type,
                target=req.target, count=req.count, radius=req.radius,
                x=req.x, y=req.y, z=req.z, extra=req.extra,
            )
            shared_state.push_event({
                "type": "directive_sent",
                "bot": req.bot,
                "directive": req.directive_type,
                "target": req.target,
                "source": "dashboard",
            })
            return {"ok": True, "result": result}
        except Exception as e:
            return {"error": str(e)}

    # ── REST: stop a bot ──

    @app.post("/api/bots/{name}/stop")
    async def stop_bot(name: str):
        if not _api_module:
            return {"error": "agent not connected"}
        try:
            await asyncio.to_thread(_api_module.stop, name)
            await asyncio.to_thread(_api_module.cancel_directive, name)
            shared_state.push_event({
                "type": "bot_stopped", "bot": name, "source": "dashboard",
            })
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    # ── REST: directive catalog (for dropdown menus) ──

    @app.get("/api/directives")
    async def list_directives():
        return {"directives": DIRECTIVE_CATALOG}

    # ── REST: task board ──

    @app.get("/api/tasks")
    async def get_tasks():
        if not _taskboard:
            return {"tasks": [], "error": "task board unavailable"}
        try:
            tasks = _taskboard.list_active(limit=50)
            return {"tasks": tasks}
        except Exception as e:
            return {"error": str(e)}

    # ── REST: transmute registry ──

    @app.get("/api/transmute")
    async def get_transmute():
        if not _transmute:
            return {"items": [], "error": "transmute DB unavailable"}
        try:
            items = _transmute.get_all()
            return {"items": [{"item_id": k, "xp_cost": v} for k, v in items.items()]}
        except Exception as e:
            return {"error": str(e)}

    # ── REST: container registry ──

    @app.get("/api/containers")
    async def get_containers():
        if not _container_db:
            return {"containers": [], "error": "container DB unavailable"}
        try:
            raw = _container_db.get_all()
            containers = []
            for cid, info in raw.items():
                containers.append({"id": cid, **info})
            return {"containers": containers}
        except Exception as e:
            return {"error": str(e)}

    # ── REST: container contents (live from mod API) ──

    @app.get("/api/containers/{x}/{y}/{z}/contents")
    async def get_container_contents(x: int, y: int, z: int):
        if not _api_module:
            return {"error": "agent not connected"}
        try:
            bots = list(shared_state.snapshot()["bots"].keys())
            if not bots:
                return {"error": "no bots online"}
            result = await asyncio.to_thread(_api_module.container, bots[0], x, y, z)
            return result
        except Exception as e:
            return {"error": str(e)}

    # ── REST: waypoints ──

    @app.get("/api/waypoints")
    async def get_waypoints():
        if not _waypoints_module:
            return {"waypoints": []}
        try:
            wps = _waypoints_module.list_waypoints()
            return {"waypoints": wps}
        except Exception as e:
            return {"error": str(e)}

    @app.post("/api/waypoints")
    async def create_waypoint(req: WaypointRequest):
        if not _waypoints_module:
            return {"error": "waypoints unavailable"}
        try:
            _waypoints_module.set_waypoint(
                req.name, req.x, req.y, req.z,
                dimension=req.dimension, set_by=req.set_by,
            )
            shared_state.push_event({
                "type": "waypoint_set", "name": req.name,
                "x": req.x, "y": req.y, "z": req.z,
                "dimension": req.dimension,
            })
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    @app.delete("/api/waypoints")
    async def delete_waypoint(req: WaypointDeleteRequest):
        if not _waypoints_module:
            return {"error": "waypoints unavailable"}
        try:
            ok = _waypoints_module.delete_waypoint(req.name)
            if ok:
                shared_state.push_event({"type": "waypoint_deleted", "name": req.name})
            return {"ok": ok}
        except Exception as e:
            return {"error": str(e)}

    # ── REST: server health (passthrough to mod API) ──

    @app.get("/api/health")
    async def health():
        if not _api_module:
            return {"status": "agent_disconnected"}
        try:
            h = await asyncio.to_thread(_api_module.health)
            return h
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    # ── REST: online players ──

    @app.get("/api/players")
    async def get_players():
        if not _api_module:
            return {"players": []}
        try:
            result = await asyncio.to_thread(_api_module.players)
            return {"players": result.get("players", [])}
        except Exception as e:
            return {"players": [], "error": str(e)}

    # ── REST: dimensions ──

    @app.get("/api/dimensions")
    async def get_dimensions():
        if not _api_module:
            return {"dimensions": []}
        try:
            result = await asyncio.to_thread(_api_module.dimensions)
            return {"dimensions": result.get("dimensions", [])}
        except Exception as e:
            return {"dimensions": [], "error": str(e)}

    # ── REST: terrain ──

    @app.get("/api/terrain")
    async def get_terrain(
        dimension: str = Query("minecraft:overworld"),
        cx: int = Query(0), cz: int = Query(0),
        radius: int = Query(100),
    ):
        if not _terrain_db:
            return {"blocks": [], "error": "terrain DB unavailable"}
        try:
            blocks = _terrain_db.get_around(dimension, cx, cz, radius=radius, limit=15000)
            return {"blocks": blocks, "dimension": dimension}
        except Exception as e:
            return {"blocks": [], "error": str(e)}

    @app.get("/api/terrain/stats")
    async def terrain_stats():
        if not _terrain_db:
            return {"stats": {}}
        try:
            return {"stats": _terrain_db.stats()}
        except Exception as e:
            return {"stats": {}, "error": str(e)}

    # ── REST: events ──

    @app.get("/api/events")
    async def get_events(since: float = Query(0)):
        return {"events": shared_state.events_since(since)}

    # ── SPA: serve frontend ──

    if STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            file_path = STATIC_DIR / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(STATIC_DIR / "index.html")

    return app


def start_dashboard(port: int, api_mod, agent_mod, tb, tx, cdb, wp, tdb=None):
    _bind_agent_refs(api_mod, agent_mod, tb, tx, cdb, wp, tdb)
    app = create_app()

    def _run():
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

    t = threading.Thread(target=_run, name="dashboard", daemon=True)
    t.start()
    print(f"[dashboard] Started on port {port}")
    return t
