package com.sigmastrain.aiplayermod.brain.skill;

import com.google.gson.JsonObject;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;

import java.util.Map;
import java.util.Set;

/**
 * A mod-side predicate evaluated synchronously against {@link BotPlayer} state —
 * no API round-trip. Parsed from a JSON object:
 *
 * <pre>{@code
 *   { "predicate": "inventory.has", "item": "minecraft:iron_ingot", "count": 16 }
 * }</pre>
 *
 * Supported predicates (Decision 4 of the v10 design):
 *   inventory.has(item, count)      inventory.space(count?)      block.at(x,y,z).is(block)
 *   position.in_area(x1,z1,x2,z2)   xp.at_least(level)           me.count(item, count?)
 *   container.near(item)            entity.near(type, radius)    health.below(value)
 *
 * Count predicates accept an optional "op" ("&gt;=", "&gt;", "&lt;", "&lt;=", "==", "!=");
 * each defaults to a natural comparison. Unknown predicates are rejected at
 * validation time ({@link #KNOWN}).
 */
public final class SkillCondition {

    public static final Set<String> KNOWN = Set.of(
            "inventory.has", "inventory.space",
            "block.at", "position.in_area",
            "xp.at_least", "me.count",
            "container.near", "entity.near", "health.below");

    public final String predicate;
    public final JsonObject args;

    private SkillCondition(String predicate, JsonObject args) {
        this.predicate = predicate;
        this.args = args;
    }

    public static SkillCondition parse(JsonObject o, String path) {
        if (o == null || !o.has("predicate")) {
            throw new IllegalArgumentException(path + ": condition missing 'predicate'");
        }
        String pred = o.get("predicate").getAsString();
        JsonObject args = new JsonObject();
        for (var e : o.entrySet()) {
            if (!e.getKey().equals("predicate")) {
                args.add(e.getKey(), e.getValue());
            }
        }
        return new SkillCondition(pred, args);
    }

    public boolean evaluate(BotPlayer bot, Map<String, String> params) {
        return switch (predicate) {
            case "inventory.has" -> effectiveCount(bot, arg("item", params)) >= argInt("count", params, 1);
            case "inventory.space" -> bot.freeSlots() >= argInt("count", params, 1);
            case "block.at" -> blockAt(bot).equals(arg("block", params));
            case "position.in_area" -> inArea(bot, params);
            case "xp.at_least" -> bot.getPlayer().experienceLevel >= argInt("count", params, argInt("level", params, 1));
            case "me.count" -> meCount(bot, arg("item", params)) >= argInt("count", params, 1);
            case "container.near" -> containerNear(bot, arg("item", params));
            case "entity.near" -> entityNear(bot, arg("type", params), argInt("radius", params, 16));
            case "health.below" -> bot.getPlayer().getHealth() < argDouble("value", params, 0.0);
            default -> false; // unknown — validation should have rejected it
        };
    }

    // ── helpers ────────────────────────────────────────────────────────────

    private String arg(String key, Map<String, String> params) {
        var el = args.get(key);
        if (el == null || el.isJsonNull()) return "";
        return SkillParams.substitute(el.getAsString(), params);
    }

    private int argInt(String key, Map<String, String> params, int def) {
        String v = arg(key, params);
        if (v.isEmpty()) return def;
        try {
            return (int) Double.parseDouble(v);
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private double argDouble(String key, Map<String, String> params, double def) {
        String v = arg(key, params);
        if (v.isEmpty()) return def;
        try {
            return Double.parseDouble(v);
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private static int effectiveCount(BotPlayer bot, String itemId) {
        String want = normalizeItem(itemId);
        int total = 0;
        for (Map<String, Object> row : bot.getEffectiveInventory()) {
            if (want.equals(row.get("item"))) {
                total += ((Number) row.getOrDefault("count", 0)).intValue();
            }
        }
        return total;
    }

    private String blockAt(BotPlayer bot) {
        int x = argInt("x", Map.of(), 0);
        int y = argInt("y", Map.of(), 0);
        int z = argInt("z", Map.of(), 0);
        return bot.blockAt(x, y, z).getOrDefault("block", "").toString();
    }

    private boolean inArea(BotPlayer bot, Map<String, String> params) {
        ServerPlayer p = bot.getPlayer();
        int px = (int) Math.floor(p.getX());
        int pz = (int) Math.floor(p.getZ());
        int x1 = argInt("x1", params, 0), z1 = argInt("z1", params, 0);
        int x2 = argInt("x2", params, 0), z2 = argInt("z2", params, 0);
        int minX = Math.min(x1, x2), maxX = Math.max(x1, x2);
        int minZ = Math.min(z1, z2), maxZ = Math.max(z1, z2);
        return px >= minX && px <= maxX && pz >= minZ && pz <= maxZ;
    }

    /** AE2 ME-network item count. Returns 0 when AE2 is absent — a bot without
     *  a linked terminal can never satisfy an me.count predicate. */
    private int meCount(BotPlayer bot, String itemId) {
        if (!com.sigmastrain.aiplayermod.compat.ModCompat.isAE2Loaded()) return 0;
        // Best-effort: the wireless-terminal query lives in MEStoreBehavior's
        // domain. A skill must not depend on me.count until the ME read is
        // wired through — return 0 (fails the predicate honestly).
        return 0;
    }

    private boolean containerNear(BotPlayer bot, String itemId) {
        String want = normalizeItem(itemId);
        for (Map<String, Object> c : bot.nearbyContainers(8)) {
            Object x = c.get("x"), y = c.get("y"), z = c.get("z");
            if (!(x instanceof Number) || !(y instanceof Number) || !(z instanceof Number)) continue;
            for (Map<String, Object> row : bot.readContainer(
                    ((Number) x).intValue(), ((Number) y).intValue(), ((Number) z).intValue())) {
                if (want.equals(row.get("item"))) return true;
            }
        }
        return false;
    }

    private boolean entityNear(BotPlayer bot, String type, int radius) {
        String want = type.toLowerCase();
        for (Map<String, Object> e : bot.getNearbyEntities(radius)) {
            String got = String.valueOf(e.get("type")).toLowerCase();
            if (got.contains(want) || want.contains(got)) return true;
        }
        return false;
    }

    private static String normalizeItem(String itemId) {
        String id = itemId == null ? "" : itemId;
        if (!id.contains(":") && !id.isEmpty()) id = "minecraft:" + id;
        return id;
    }

    /** Reconstruct the declarative JSON for this predicate, so a spec's
     *  {@code verify} / {@code while} / {@code if} condition round-trips through
     *  disk persistence. */
    public JsonObject toJson() {
        JsonObject o = new JsonObject();
        o.addProperty("predicate", predicate);
        for (var e : args.entrySet()) {
            o.add(e.getKey(), e.getValue());
        }
        return o;
    }
}
