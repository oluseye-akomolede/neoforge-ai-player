#!/usr/bin/env python3
"""
AI Player Agent — connects ollama to the NeoForge AI Player Mod.
Supports multiple bots from a single process, each with its own
observe → think → act loop running in a separate thread.
"""

import json
import os
import threading
import time
import sys
import api
import brain
import memory as mem_module
import prompts
import semantic_memory as sem
from config import (
    TICK_DELAY, BUSY_POLL_DELAY,
    OBSERVE_ENTITY_RADIUS, OBSERVE_BLOCK_RADIUS,
    MAX_CHAT_HISTORY, MAX_CONVERSATION, OLLAMA_URL, PG_DSN,
)

CHAT_POLL_INTERVAL = 0.25


class BotRunner:
    """Runs the observe/think/act loop for a single bot in its own thread."""

    def __init__(self, profile):
        self.profile = profile
        self.name = profile["name"]
        self.model = profile.get("model", "llama3.1:8b")
        self.chat_history = []
        self.conversation_history = []
        self.memory_entries = []
        self.system_prompt = ""
        self.semantic_mem = None
        self._thread = None
        self._chat_thread = None
        self._stop_event = threading.Event()
        self._chat_event = threading.Event()
        self._lock = threading.Lock()
        self._memory_file = os.path.join(
            os.path.dirname(__file__), f"memory_{self.name.lower()}.json"
        )

    def start(self):
        api.spawn(self.name)
        time.sleep(0.5)
        self.memory_entries = mem_module.load_from(self._memory_file)

        try:
            self.semantic_mem = sem.SemanticMemory(self.name, OLLAMA_URL, PG_DSN)
            self.semantic_mem.connect()
            stats = self.semantic_mem.stats()
            print(f"[{self.name}] Semantic memory: {stats['total']} memories ({stats['cached']} cached)")
        except Exception as e:
            print(f"[{self.name}] Semantic memory unavailable: {e}")
            self.semantic_mem = None

        self.system_prompt = prompts.build_system_prompt(self.profile, self.memory_entries)
        self._stop_event.clear()
        self._chat_event.clear()
        self._thread = threading.Thread(target=self._loop, name=f"bot-{self.name}", daemon=True)
        self._chat_thread = threading.Thread(target=self._chat_poll_loop, name=f"chat-{self.name}", daemon=True)
        self._thread.start()
        self._chat_thread.start()
        print(f"[{self.name}] Started (model={self.model})")

    def stop(self):
        self._stop_event.set()
        self._chat_event.set()
        try:
            api.stop(self.name)
            api.despawn(self.name)
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=10)
        if self._chat_thread:
            self._chat_thread.join(timeout=5)
        if self.semantic_mem:
            self.semantic_mem.close()
        print(f"[{self.name}] Stopped")

    def _chat_poll_loop(self):
        """Fast-polling thread that watches for incoming chat and signals the main loop."""
        while not self._stop_event.is_set():
            try:
                inbox = api.chat_inbox(self.name)
                msgs = inbox.get("messages", [])
                if msgs:
                    with self._lock:
                        for msg in msgs:
                            entry = f"{msg['sender']}: {msg['message']}"
                            self.chat_history.append(entry)
                            if len(self.chat_history) > MAX_CHAT_HISTORY:
                                self.chat_history.pop(0)
                    self._chat_event.set()
            except Exception:
                pass
            self._stop_event.wait(CHAT_POLL_INTERVAL)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._wait_for_idle_or_chat(timeout=10)
                obs = self._observe()

                # Recall relevant semantic memories for this observation
                sem_context = ""
                if self.semantic_mem:
                    try:
                        sem_context = self.semantic_mem.recall_for_prompt(obs[:500], limit=6)
                    except Exception as e:
                        print(f"[{self.name}/sem] recall error: {e}")

                prompt = prompts.build_system_prompt(self.profile, self.memory_entries, sem_context)
                response = brain.think(self.model, prompt, obs, self.conversation_history)

                thoughts = response.get("thoughts", "")
                actions = response.get("actions", [])
                chat_msg = response.get("chat")
                remember = response.get("remember")

                print(f"\n[{self.name}/think] {thoughts}")

                if chat_msg:
                    with self._lock:
                        self.chat_history.append(f"{self.name}: {chat_msg}")
                        if len(self.chat_history) > MAX_CHAT_HISTORY:
                            self.chat_history.pop(0)
                    api.chat(self.name, chat_msg)
                    print(f"[{self.name}/chat] {chat_msg}")

                if remember:
                    # Store in flat file (legacy)
                    self.memory_entries = mem_module.add_to(
                        self.memory_entries, remember, self._memory_file
                    )
                    # Store in semantic memory
                    if self.semantic_mem:
                        try:
                            category = _parse_memory_category(remember)
                            clean = _strip_category_prefix(remember)
                            mid = self.semantic_mem.store(clean, category=category)
                            print(f"[{self.name}/sem] stored [{category}] id={mid}")
                        except Exception as e:
                            print(f"[{self.name}/sem] store error: {e}")

                    print(f"[{self.name}/memory] {remember}")

                self.conversation_history.append({"role": "user", "content": obs})
                self.conversation_history.append({"role": "assistant", "content": json.dumps(response)})
                while len(self.conversation_history) > MAX_CONVERSATION * 2:
                    self.conversation_history.pop(0)
                    self.conversation_history.pop(0)

                if actions:
                    self._execute_actions(actions)

                self._stop_event.wait(TICK_DELAY)

            except Exception as e:
                print(f"[{self.name}/error] {e}")
                self._stop_event.wait(TICK_DELAY * 2)

    def _wait_for_idle_or_chat(self, timeout=10):
        """Wait for actions to finish, but interrupt immediately if chat arrives."""
        start = time.time()
        while time.time() - start < timeout:
            if self._stop_event.is_set():
                return
            if self._chat_event.is_set():
                self._chat_event.clear()
                return
            state = api.actions(self.name)
            is_idle = state.get("queued", 0) == 0 and state.get("current", "idle") == "idle"
            if is_idle:
                return
            self._stop_event.wait(BUSY_POLL_DELAY)

    def _observe(self):
        status = api.status(self.name)
        inv = api.inventory(self.name)
        ents = api.entities(self.name, OBSERVE_ENTITY_RADIUS)
        blks = api.blocks(self.name, OBSERVE_BLOCK_RADIUS)
        action_state = api.actions(self.name)

        with self._lock:
            chat_snapshot = list(self.chat_history)
            new_messages = [m for m in chat_snapshot if not m.startswith(f"{self.name}:")]
            new_messages = new_messages[-5:]

        return prompts.build_observation(
            status, inv, ents, blks, action_state, chat_snapshot, new_messages
        )

    def _execute_actions(self, actions):
        for act in actions:
            name = act.get("action", "")
            params = act.get("params", {})
            try:
                self._execute_one(name, params)
                print(f"  [{self.name}] -> {name}: ok")
            except Exception as e:
                print(f"  [{self.name}] -> {name}: ERROR {e}")

    def _execute_one(self, name, p):
        bot = self.name
        match name:
            case "goto":
                return api.goto(bot, p["x"], p["y"], p["z"], p.get("distance", 2.0), p.get("sprint", True))
            case "fly_to":
                return api.fly_to(bot, p["x"], p["y"], p["z"], p.get("distance", 2.0), p.get("speed", 0.5))
            case "look":
                return api.look(bot, p["x"], p["y"], p["z"])
            case "teleport":
                return api.teleport(bot, p["x"], p["y"], p["z"], p.get("dimension"))
            case "follow":
                return api.follow(bot, p["target"], p.get("distance", 3.0), p.get("radius", 32.0))
            case "attack":
                return api.attack(bot, p["target"], p.get("radius", 16.0))
            case "mine":
                return api.mine(bot, p["x"], p["y"], p["z"])
            case "place":
                return api.place(bot, p["x"], p["y"], p["z"])
            case "craft":
                return api.craft(bot, p["item"], p.get("count", 1))
            case "equip":
                return api.equip(bot, p["slot"])
            case "use":
                return api.use_item(bot)
            case "drop":
                return api.drop(bot, p["slot"], p.get("count", 64))
            case "collect":
                return api.collect(bot, p.get("radius", 16.0))
            case "swap":
                return api.swap(bot, p["from"], p["to"])
            case "find_blocks":
                return api.find_blocks(bot, p["block"], p.get("radius", 32), p.get("max", 10))
            case "find_entities":
                return api.find_entities(bot, p["target"], p.get("radius", 32.0))
            case "container":
                return api.container(bot, p["x"], p["y"], p["z"])
            case "container_insert":
                return api.container_insert(bot, p["x"], p["y"], p["z"], p["slot"], p.get("count", 64))
            case "container_extract":
                return api.container_extract(bot, p["x"], p["y"], p["z"], p["slot"], p.get("count", 64))
            case "list_recipes":
                return api.list_recipes(bot, p.get("filter", ""), p.get("craftable_only", False))
            case "craft_chain":
                return api.craft_chain(bot, p["item"], p.get("count", 1))
            case "chat":
                msg = p["message"]
                with self._lock:
                    self.chat_history.append(f"{bot}: {msg}")
                    if len(self.chat_history) > MAX_CHAT_HISTORY:
                        self.chat_history.pop(0)
                return api.chat(bot, msg)
            case "stop":
                return api.stop(bot)
            case _:
                return {"error": f"Unknown action: {name}"}


def _parse_memory_category(text):
    """Extract category from '[category] content' format."""
    text = text.strip()
    if text.startswith("["):
        end = text.find("]")
        if end > 0:
            cat = text[1:end].lower().strip()
            if cat in ("location", "instruction", "knowledge", "event"):
                return cat
    return "knowledge"


def _strip_category_prefix(text):
    """Remove '[category] ' prefix if present."""
    text = text.strip()
    if text.startswith("["):
        end = text.find("]")
        if end > 0:
            return text[end + 1:].strip()
    return text


def load_profiles():
    """Load all profile JSON files from the profiles directory."""
    profiles_dir = os.path.join(os.path.dirname(__file__), "profiles")
    profiles = []
    for fname in sorted(os.listdir(profiles_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(profiles_dir, fname)) as f:
                profiles.append(json.load(f))
    return profiles


def run():
    print(f"[agent] Checking ollama at {OLLAMA_URL}...")
    ok, models = brain.check_ollama(OLLAMA_URL)
    if ok:
        print(f"[agent] Ollama models: {', '.join(models)}")
    else:
        print(f"[error] Cannot reach ollama: {models}")

    print(f"[agent] Connecting to mod API...")
    try:
        h = api.health()
        print(f"[agent] Mod API: {h}")
    except Exception as e:
        print(f"[error] Cannot reach mod API: {e}")
        sys.exit(1)

    # Despawn any stale bots from a previous agent run
    try:
        existing = api.list_bots().get("bots", [])
        if existing:
            print(f"[agent] Cleaning up {len(existing)} stale bot(s): {existing}")
            for name in existing:
                api.despawn(name)
    except Exception:
        pass

    profiles = load_profiles()
    print(f"[agent] Found {len(profiles)} bot profile(s): {[p['name'] for p in profiles]}")

    runners = []
    for profile in profiles:
        runner = BotRunner(profile)
        runner.start()
        runners.append(runner)

    print(f"[agent] All bots started (tick={TICK_DELAY}s)")
    print("=" * 50)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[agent] Shutting down all bots...")
        for runner in runners:
            runner.stop()


if __name__ == "__main__":
    run()
