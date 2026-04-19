import requests
from config import MOD_API_URL, MOD_API_KEY


def _headers():
    h = {"Content-Type": "application/json"}
    if MOD_API_KEY:
        h["X-Api-Key"] = MOD_API_KEY
    return h


def _get(path):
    r = requests.get(f"{MOD_API_URL}{path}", headers=_headers(), timeout=5)
    return r.json()


def _post(path, data=None):
    r = requests.post(f"{MOD_API_URL}{path}", json=data or {}, headers=_headers(), timeout=5)
    return r.json()


def _delete(path, data=None):
    r = requests.delete(f"{MOD_API_URL}{path}", json=data or {}, headers=_headers(), timeout=5)
    return r.json()


# ── Bot lifecycle ──

def health():
    return _get("/health")

def spawn(name):
    return _post("/bots", {"name": name})

def despawn(name):
    return _delete("/bots", {"name": name})

def list_bots():
    return _get("/bots")


# ── Observation ──

def status(bot):
    return _get(f"/bot/{bot}/status")

def inventory(bot):
    return _get(f"/bot/{bot}/inventory")

def entities(bot, radius=24.0):
    return _post(f"/bot/{bot}/entities", {"radius": radius})

def blocks(bot, radius=8):
    return _post(f"/bot/{bot}/blocks", {"radius": radius})

def find_blocks(bot, block, radius=32, max_count=10):
    return _post(f"/bot/{bot}/find_blocks", {"block": block, "radius": radius, "max": max_count})

def find_entities(bot, target, radius=32.0):
    return _post(f"/bot/{bot}/find_entities", {"target": target, "radius": radius})

def actions(bot):
    return _get(f"/bot/{bot}/actions")


# ── Actions ──

def chat(bot, message):
    return _post(f"/bot/{bot}/chat", {"message": message})

def goto(bot, x, y, z, distance=2.0, sprint=False):
    return _post(f"/bot/{bot}/goto", {"x": x, "y": y, "z": z, "distance": distance, "sprint": sprint})

def fly_to(bot, x, y, z, distance=2.0, speed=0.5):
    return _post(f"/bot/{bot}/fly_to", {"x": x, "y": y, "z": z, "distance": distance, "speed": speed})

def attack(bot, target, radius=16.0):
    return _post(f"/bot/{bot}/attack", {"target": target, "radius": radius})

def mine(bot, x, y, z):
    return _post(f"/bot/{bot}/mine", {"x": x, "y": y, "z": z})

def place(bot, x, y, z):
    return _post(f"/bot/{bot}/place", {"x": x, "y": y, "z": z})

def craft(bot, item, count=1):
    return _post(f"/bot/{bot}/craft", {"item": item, "count": count})

def equip(bot, slot):
    return _post(f"/bot/{bot}/equip", {"slot": slot})

def use_item(bot):
    return _post(f"/bot/{bot}/use")

def drop(bot, slot, count=64):
    return _post(f"/bot/{bot}/drop", {"slot": slot, "count": count})

def collect(bot, radius=16.0):
    return _post(f"/bot/{bot}/collect", {"radius": radius})

def follow(bot, target, distance=3.0, radius=32.0, sprint=False):
    return _post(f"/bot/{bot}/follow", {"target": target, "distance": distance, "radius": radius, "sprint": sprint})

def look(bot, x, y, z):
    return _post(f"/bot/{bot}/look", {"x": x, "y": y, "z": z})

def teleport(bot, x, y, z, dimension=None):
    data = {"x": x, "y": y, "z": z}
    if dimension:
        data["dimension"] = dimension
    return _post(f"/bot/{bot}/teleport", data)

def swap(bot, from_slot, to_slot):
    return _post(f"/bot/{bot}/swap", {"from": from_slot, "to": to_slot})

def container(bot, x, y, z):
    return _post(f"/bot/{bot}/container", {"x": x, "y": y, "z": z})

def container_insert(bot, x, y, z, slot, count=64):
    return _post(f"/bot/{bot}/container_insert", {"x": x, "y": y, "z": z, "slot": slot, "count": count})

def container_extract(bot, x, y, z, slot, count=64):
    return _post(f"/bot/{bot}/container_extract", {"x": x, "y": y, "z": z, "slot": slot, "count": count})

def list_recipes(bot, filter_str="", craftable_only=False):
    return _post(f"/bot/{bot}/list_recipes", {"filter": filter_str, "craftable_only": craftable_only})

def craft_chain(bot, item, count=1):
    return _post(f"/bot/{bot}/craft_chain", {"item": item, "count": count})

def stop(bot):
    return _post(f"/bot/{bot}/stop")

def chat_inbox(bot):
    return _get(f"/bot/{bot}/chat_inbox")
