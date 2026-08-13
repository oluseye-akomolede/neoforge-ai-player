import requests
from config import MOD_API_URL, MOD_API_KEY


def _headers():
    h = {"Content-Type": "application/json"}
    if MOD_API_KEY:
        h["X-Api-Key"] = MOD_API_KEY
    # Presence beacon: the mod's overlay shows "agent down" when requests
    # with this header stop arriving. Dashboard traffic must NOT set it.
    h["X-Agent-Id"] = "aibot-agent"
    return h


def _get(path):
    r = requests.get(f"{MOD_API_URL}{path}", headers=_headers(), timeout=5)
    return r.json()


def _post(path, data=None, timeout=5):
    r = requests.post(f"{MOD_API_URL}{path}", json=data or {}, headers=_headers(), timeout=timeout)
    return r.json()


def _delete(path, data=None):
    r = requests.delete(f"{MOD_API_URL}{path}", json=data or {}, headers=_headers(), timeout=5)
    return r.json()


def get_directive(bot):
    """Current or last-completed directive as the mod reports it."""
    return _get(f"/bot/{bot}/directive")


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

def block_at(bot, x, y, z):
    return _post(f"/bot/{bot}/block_at", {"x": x, "y": y, "z": z})

# ── Vault: unbounded per-bot storage behind the 36 carried slots ──────────

def server_items(namespace=None, query=None):
    """Full item registry — every item the server has, modded included."""
    qs = []
    if namespace:
        qs.append(f"namespace={namespace}")
    if query:
        qs.append(f"query={query}")
    suffix = ("?" + "&".join(qs)) if qs else ""
    return _get(f"/server/items{suffix}")


def server_structures(namespace=None, query=None):
    """Full structure registry — every structure + structure tag the server has.

    The counterpart to server_items() for reconnaissance: structure names can't
    be hand-listed for a 300+ mod pack any more than item names could."""
    qs = []
    if namespace:
        qs.append(f"namespace={namespace}")
    if query:
        qs.append(f"query={query}")
    suffix = ("?" + "&".join(qs)) if qs else ""
    return _get(f"/server/structures{suffix}")


def locate(bot, target, chunk_radius=100, timeout=120):
    """Nearest structure of a given kind, via the world generator.

    One query out to chunk_radius*16 blocks — the same lookup /locate uses.
    This is what WIDE_SEARCH cannot do: WIDE_SEARCH scans BLOCKS, and a
    structure is not a block.

    The default 5s HTTP timeout is far too short here: a cold search through
    ungenerated chunks for a rare structure (mansion, stronghold) runs for
    seconds. Timing out client-side does not cancel the server-side search —
    it just loses the answer."""
    return _post(f"/bot/{bot}/locate",
                 {"target": target, "chunk_radius": chunk_radius}, timeout=timeout)


def tempad_share(bot, player, name="Waypoint", x=None, y=None, z=None,
                 dimension=None, color=None):
    """Write a waypoint into a player's TemPad device.

    The bot is the courier — coordinates need not come from LOCATE. Backed by
    TemPad's own PlayerPointsData (server saved data keyed by player UUID), so
    it works whether or not the player is online."""
    data = {"player": player, "name": name}
    for k, v in (("x", x), ("y", y), ("z", z), ("dimension", dimension), ("color", color)):
        if v is not None:
            data[k] = v
    return _post(f"/bot/{bot}/tempad_share", data)


def tempad_locations(player):
    """Read back a player's TemPad waypoints."""
    return _get(f"/server/tempad?player={player}")


def tempad_remove(bot, player, waypoint_id):
    """Remove a waypoint by id. A device bots can write to needs a way to
    take things out of it."""
    return _post(f"/bot/{bot}/tempad_remove", {"player": player, "id": waypoint_id})


def vault(bot):
    """Full vault manifest (merged by item id)."""
    return _get(f"/bot/{bot}/vault")

def vault_search(bot, query):
    """Substring search across vault contents."""
    return _post(f"/bot/{bot}/vault_search", {"query": query})

def effective_inventory(bot):
    """Carried + vault, merged — the bot's REAL holdings. Criteria and
    provisioning must use this, not the carried-only view."""
    return _post(f"/bot/{bot}/effective_inventory", {})

def vault_store(bot, item=None, count=None):
    """Page carried items into the vault. item=None flushes everything evictable."""
    data = {}
    if item:
        data["item"] = item
    if count is not None:
        data["count"] = count
    return _post(f"/bot/{bot}/vault_store", data)

def vault_withdraw(bot, item, count=1):
    return _post(f"/bot/{bot}/vault_withdraw", {"item": item, "count": count})

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

def equip_all(bot):
    """Smart bulk equip: bot scans inventory and puts each equippable piece
    into its proper armor/offhand slot. No slot number needed."""
    return _post(f"/bot/{bot}/equip_all", {})

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

def cancel_directive(bot, directive_id=None):
    # Pass the id of the directive you own — the mod ignores the cancel if a
    # NEWER directive is already active (D3 race guard).
    data = {"id": directive_id} if directive_id else None
    return _delete(f"/bot/{bot}/directive", data)


def me_status(bot):
    return _get(f"/bot/{bot}/me_status")


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


# ── Enchantment registry ──

def enchantment_list():
    return _get("/enchantments")


# ── Terrain scanning ──

def surface_scan(bot, radius=12):
    return _post(f"/bot/{bot}/surface_scan", {"radius": radius})

def nearby_containers(bot, radius=8):
    return _post(f"/bot/{bot}/nearby_containers", {"radius": radius})

def dimensions():
    return _get("/server/dimensions")

def players():
    return _get("/server/players")


def skills():
    """Registered skill catalog (id, description, params, verify). Server-global."""
    return _get("/skills")


# ── ME fabric (worn wireless terminal; v7 phase 6) ──

def me_status(bot):
    """Wireless ME access state + legacy nearest-interface fields."""
    return _post(f"/bot/{bot}/me_status", {})

def me_search(bot, query=""):
    return _post(f"/bot/{bot}/me_search", {"query": query})

def me_push(bot, item, count=64):
    """Carried → network via the worn terminal."""
    return _post(f"/bot/{bot}/me_push", {"item": item, "count": count})

def me_pull(bot, item, count=64):
    """Network → carried (vault overflow) via the worn terminal."""
    return _post(f"/bot/{bot}/me_pull", {"item": item, "count": count})
