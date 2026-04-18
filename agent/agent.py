#!/usr/bin/env python3
"""
AI Player Agent — connects ollama to the NeoForge AI Player Mod.
Observe → Think → Act loop, inspired by mindcraft.
"""

import json
import time
import sys
import api
import brain
import memory
import prompts
from config import (
    TICK_DELAY, BUSY_POLL_DELAY,
    OBSERVE_ENTITY_RADIUS, OBSERVE_BLOCK_RADIUS,
    MAX_CHAT_HISTORY, MAX_CONVERSATION, OLLAMA_URL,
    load_profile,
)


chat_history = []
conversation_history = []
memory_entries = []


def observe(bot_name):
    status = api.status(bot_name)
    inv = api.inventory(bot_name)
    ents = api.entities(bot_name, OBSERVE_ENTITY_RADIUS)
    blks = api.blocks(bot_name, OBSERVE_BLOCK_RADIUS)
    action_state = api.actions(bot_name)
    return prompts.build_observation(status, inv, ents, blks, action_state, chat_history)


def execute_actions(bot_name, actions):
    for act in actions:
        name = act.get("action", "")
        params = act.get("params", {})
        try:
            result = execute_one(bot_name, name, params)
            print(f"  -> {name}: ok")
        except Exception as e:
            print(f"  -> {name}: ERROR {e}")


def execute_one(bot, name, p):
    match name:
        case "goto":
            return api.goto(bot, p["x"], p["y"], p["z"], p.get("distance", 2.0))
        case "look":
            return api.look(bot, p["x"], p["y"], p["z"])
        case "teleport":
            return api.teleport(bot, p["x"], p["y"], p["z"])
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
        case "chat":
            msg = p["message"]
            chat_history.append(f"{bot}: {msg}")
            if len(chat_history) > MAX_CHAT_HISTORY:
                chat_history.pop(0)
            return api.chat(bot, msg)
        case "stop":
            return api.stop(bot)
        case _:
            return {"error": f"Unknown action: {name}"}


def wait_for_idle(bot_name, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        state = api.actions(bot_name)
        if state.get("queued", 0) == 0 and state.get("current", "idle") == "idle":
            return True
        time.sleep(BUSY_POLL_DELAY)
    return False


def run():
    global memory_entries

    profile = load_profile()
    bot_name = profile["name"]
    model = profile.get("model", "llama3.1:8b")

    print(f"[agent] Profile: {bot_name} using model {model}")

    # check ollama
    print(f"[agent] Checking ollama at {OLLAMA_URL}...")
    ok, models = brain.check_ollama(OLLAMA_URL)
    if ok:
        print(f"[agent] Ollama models: {', '.join(models)}")
        if model not in models and not any(model in m for m in models):
            print(f"[warn] Model '{model}' not found in ollama. Available: {models}")
            print(f"[warn] You may need to: ollama pull {model}")
    else:
        print(f"[error] Cannot reach ollama: {models}")
        print(f"[agent] Will retry when the loop starts...")

    # connect to mod
    print(f"[agent] Connecting to mod API...")
    try:
        h = api.health()
        print(f"[agent] Mod API: {h}")
    except Exception as e:
        print(f"[error] Cannot reach mod API: {e}")
        sys.exit(1)

    # spawn bot
    print(f"[agent] Spawning bot '{bot_name}'...")
    api.spawn(bot_name)
    time.sleep(1)

    # load memory
    memory_entries = memory.load()
    print(f"[agent] Loaded {len(memory_entries)} memories")

    # build system prompt
    system = prompts.build_system_prompt(profile, memory_entries)

    print(f"[agent] Agent loop starting (tick={TICK_DELAY}s)")
    print("=" * 50)

    while True:
        try:
            # wait for bot to finish current actions
            if not wait_for_idle(bot_name, timeout=15):
                print("[agent] Bot busy, waiting...")
                time.sleep(TICK_DELAY)
                continue

            obs = observe(bot_name)

            response = brain.think(model, system, obs, conversation_history)

            thoughts = response.get("thoughts", "")
            actions = response.get("actions", [])
            chat_msg = response.get("chat")
            remember = response.get("remember")

            print(f"\n[think] {thoughts}")

            # handle chat
            if chat_msg:
                chat_history.append(f"{bot_name}: {chat_msg}")
                if len(chat_history) > MAX_CHAT_HISTORY:
                    chat_history.pop(0)
                api.chat(bot_name, chat_msg)
                print(f"[chat] {bot_name}: {chat_msg}")

            # handle memory
            if remember:
                memory_entries = memory.add(memory_entries, remember)
                system = prompts.build_system_prompt(profile, memory_entries)
                print(f"[memory] Saved: {remember}")

            # keep conversation context
            conversation_history.append({"role": "user", "content": obs})
            conversation_history.append({"role": "assistant", "content": json.dumps(response)})
            while len(conversation_history) > MAX_CONVERSATION * 2:
                conversation_history.pop(0)
                conversation_history.pop(0)

            # execute actions
            if actions:
                execute_actions(bot_name, actions)

            time.sleep(TICK_DELAY)

        except KeyboardInterrupt:
            print("\n[agent] Shutting down...")
            try:
                api.stop(bot_name)
                api.despawn(bot_name)
            except Exception:
                pass
            break
        except Exception as e:
            print(f"[error] {e}")
            time.sleep(TICK_DELAY * 3)


if __name__ == "__main__":
    run()
