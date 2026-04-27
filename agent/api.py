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


raw_get = _get
raw_post = _post
raw_delete = _delete


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

def system_chat(bot, message, color="gray"):
    return _post(f"/bot/{bot}/system_chat", {"message": message, "color": color})

def goto(bot, x, y, z, distance=2.0, sprint=False):
    return _post(f"/bot/{bot}/goto", {"x": x, "y": y, "z": z, "distance": distance, "sprint": sprint})

def fly_to(bot, x, y, z, distance=2.0, speed=0.5):
    return _post(f"/bot/{bot}/fly_to", {"x": x, "y": y, "z": z, "distance": distance, "speed": speed})

def attack(bot, target, radius=16.0):
    return _post(f"/bot/{bot}/attack", {"target": target, "radius": radius})

def combat_mode(bot, radius=24.0, hostile_only=True, target=None):
    data = {"radius": radius, "hostile_only": hostile_only}
    if target:
        data["target"] = target
    return _post(f"/bot/{bot}/combat_mode", data)

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

def container_extract(bot, x, y, z, slot=None, item=None, count=64):
    data = {"x": x, "y": y, "z": z, "count": count}
    if item:
        data["item"] = item
    elif slot is not None:
        data["slot"] = slot
    return _post(f"/bot/{bot}/container_extract", data)

def list_recipes(bot, filter_str="", craftable_only=False):
    return _post(f"/bot/{bot}/list_recipes", {"filter": filter_str, "craftable_only": craftable_only})

def craft_chain(bot, item, count=1):
    return _post(f"/bot/{bot}/craft_chain", {"item": item, "count": count})

def stop(bot):
    return _post(f"/bot/{bot}/stop")

def chat_inbox(bot):
    return _get(f"/bot/{bot}/chat_inbox")

def inject_chat(bot, sender, message):
    return _post(f"/bot/{bot}/inject_chat", {"sender": sender, "message": message})


# ── Magic / enchanting / brewing ──

def anvil(bot, input_slot, material_slot=-1, name=None):
    data = {"input_slot": input_slot, "material_slot": material_slot}
    if name:
        data["name"] = name
    return _post(f"/bot/{bot}/anvil", data)

def smithing(bot, template_slot, base_slot, addition_slot):
    return _post(f"/bot/{bot}/smithing", {
        "template_slot": template_slot,
        "base_slot": base_slot,
        "addition_slot": addition_slot,
    })

def brew(bot, ingredient_slot, bottle_slots, fuel_slot=-1):
    return _post(f"/bot/{bot}/brew", {
        "ingredient_slot": ingredient_slot,
        "bottle_slots": bottle_slots,
        "fuel_slot": fuel_slot,
    })

def enchant(bot, item_slot, lapis_slot, option=2):
    return _post(f"/bot/{bot}/enchant", {
        "item_slot": item_slot,
        "lapis_slot": lapis_slot,
        "option": option,
    })

def xp_status(bot):
    return _get(f"/bot/{bot}/xp")

def xp_give(bot, levels=0, points=0):
    return _post(f"/bot/{bot}/xp", {"levels": levels, "points": points})

def meditate(bot, levels=10):
    return _post(f"/bot/{bot}/meditate", {"levels": levels})

def conjure(bot, item, count=1):
    return _post(f"/bot/{bot}/conjure", {"item": item, "count": count})

def repair(bot, slot):
    return _post(f"/bot/{bot}/repair", {"slot": slot})

def smelt(bot, input_slot, fuel_slot, count=1):
    return _post(f"/bot/{bot}/smelt", {"input_slot": input_slot, "fuel_slot": fuel_slot, "count": count})

def trade(bot, trade_index=-1, times=1):
    return _post(f"/bot/{bot}/trade", {"trade_index": trade_index, "times": times})


# ── Shop ──

def shop_list(bot=None):
    if bot:
        return _get(f"/bot/{bot}/shop_list")
    return _get("/shop")

def shop_buy(bot, item, count=1):
    return _post(f"/bot/{bot}/shop_buy", {"item": item, "count": count})

def shop_add(item, price, max_per_purchase=64, category="general"):
    return _post("/shop", {"item": item, "price": price, "max_per_purchase": max_per_purchase, "category": category})

def shop_remove(item):
    return _delete("/shop", {"item": item})


# ── Item transfer ──

def send_item(bot, slot, target, count=64):
    return _post(f"/bot/{bot}/send_item", {"slot": slot, "target": target, "count": count})


# ── Brain / Directives (L1) ──

def set_directive(bot, directive_type, target=None, count=None, radius=None, x=None, y=None, z=None, extra=None):
    data = {"type": directive_type}
    if target is not None:
        data["target"] = target
    if count is not None:
        data["count"] = count
    if radius is not None:
        data["radius"] = radius
    if x is not None and y is not None and z is not None:
        data["x"] = x
        data["y"] = y
        data["z"] = z
    if extra:
        data["extra"] = extra
    return _post(f"/bot/{bot}/directive", data)

def get_brain(bot):
    return _get(f"/bot/{bot}/brain")

def cancel_directive(bot):
    return _delete(f"/bot/{bot}/directive")


# ── Transmute registry ──

def transmute_list():
    return _get("/transmute")

def transmute_get(item_id):
    return _get(f"/transmute?item={item_id}")

def transmute_register(item_id, xp_cost, source="agent"):
    return _post("/transmute", {"item": item_id, "xp_cost": xp_cost, "source": source})

def transmute_remove(item_id):
    return _delete("/transmute", {"item": item_id})

def transmute_names():
    return _get("/transmute/names")


# ── Terrain scanning ──

def surface_scan(bot, radius=12):
    return _post(f"/bot/{bot}/surface_scan", {"radius": radius})

def nearby_containers(bot, radius=8):
    return _post(f"/bot/{bot}/nearby_containers", {"radius": radius})

def dimensions():
    return _get("/server/dimensions")
