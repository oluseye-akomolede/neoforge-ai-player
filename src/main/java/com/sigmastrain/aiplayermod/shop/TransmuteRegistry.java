package com.sigmastrain.aiplayermod.shop;

import com.google.gson.*;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.Rarity;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Server-wide registry of discovered items and their XP transmutation values.
 * Any item a bot encounters in its inventory gets registered here automatically.
 * Modded items get heuristic XP values; vanilla items use ConjureAction's table when available.
 */
public class TransmuteRegistry {
    private static final Map<String, TransmuteEntry> registry = new ConcurrentHashMap<>();
    private static Path configPath;
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    private static volatile boolean dirty = false;
    private static long lastSaveTick = 0;
    private static final long SAVE_INTERVAL_TICKS = 600; // save at most every 30 seconds

    public record TransmuteEntry(String itemId, int xpCost, String source, long discoveredTick) {}

    public static void init(Path serverDir) {
        configPath = serverDir.resolve("config").resolve("aiplayermod-transmute.json");
        loadConfig();
    }

    public static void loadConfig() {
        registry.clear();
        if (configPath == null || !Files.exists(configPath)) {
            AIPlayerMod.LOGGER.info("No transmute registry at {}, starting empty", configPath);
            return;
        }
        try (Reader r = Files.newBufferedReader(configPath)) {
            JsonObject root = JsonParser.parseReader(r).getAsJsonObject();
            JsonArray items = root.getAsJsonArray("items");
            if (items == null) return;
            for (JsonElement el : items) {
                JsonObject obj = el.getAsJsonObject();
                String id = obj.get("item").getAsString();
                int cost = obj.get("xp_cost").getAsInt();
                String source = obj.has("source") ? obj.get("source").getAsString() : "loaded";
                long tick = obj.has("discovered_tick") ? obj.get("discovered_tick").getAsLong() : 0;
                registry.put(id, new TransmuteEntry(id, cost, source, tick));
            }
            AIPlayerMod.LOGGER.info("Loaded {} transmutable items from registry", registry.size());
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Failed to load transmute registry", e);
        }
    }

    public static void saveConfig() {
        if (configPath == null) return;
        try {
            Files.createDirectories(configPath.getParent());
            JsonObject root = new JsonObject();
            JsonArray items = new JsonArray();
            for (TransmuteEntry entry : registry.values()) {
                JsonObject obj = new JsonObject();
                obj.addProperty("item", entry.itemId());
                obj.addProperty("xp_cost", entry.xpCost());
                obj.addProperty("source", entry.source());
                obj.addProperty("discovered_tick", entry.discoveredTick());
                items.add(obj);
            }
            root.addProperty("count", registry.size());
            root.add("items", items);
            try (Writer w = Files.newBufferedWriter(configPath)) {
                GSON.toJson(root, w);
            }
            dirty = false;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Failed to save transmute registry", e);
        }
    }

    /**
     * Called from server tick — saves if dirty and interval has passed.
     */
    public static void tickSave(long currentTick) {
        if (dirty && currentTick - lastSaveTick >= SAVE_INTERVAL_TICKS) {
            lastSaveTick = currentTick;
            saveConfig();
        }
    }

    /**
     * Register a discovered item if not already known. Returns true if newly added.
     */
    public static boolean discover(ItemStack stack, String source, long tick) {
        if (stack.isEmpty()) return false;
        String itemId = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
        if (registry.containsKey(itemId)) return false;

        int cost = estimateXpCost(stack);
        registry.put(itemId, new TransmuteEntry(itemId, cost, source, tick));
        dirty = true;
        AIPlayerMod.LOGGER.info("Transmute registry: discovered {} (cost={} XP, source={})", itemId, cost, source);
        return true;
    }

    /**
     * Register an item by ID with explicit cost. Used by API.
     */
    public static void register(String itemId, int xpCost, String source, long tick) {
        registry.put(itemId, new TransmuteEntry(itemId, xpCost, source, tick));
        dirty = true;
    }

    public static TransmuteEntry get(String itemId) {
        return registry.get(itemId);
    }

    public static boolean isKnown(String itemId) {
        return registry.containsKey(itemId);
    }

    public static int getCost(String itemId) {
        TransmuteEntry entry = registry.get(itemId);
        return entry != null ? entry.xpCost() : -1;
    }

    public static int size() {
        return registry.size();
    }

    public static boolean remove(String itemId) {
        boolean removed = registry.remove(itemId) != null;
        if (removed) dirty = true;
        return removed;
    }

    public static List<Map<String, Object>> listAll() {
        List<Map<String, Object>> result = new ArrayList<>();
        for (TransmuteEntry entry : registry.values()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("item", entry.itemId());
            m.put("xp_cost", entry.xpCost());
            m.put("source", entry.source());
            m.put("discovered_tick", entry.discoveredTick());
            result.add(m);
        }
        result.sort(Comparator.comparing(m -> (String) m.get("item")));
        return result;
    }

    public static Map<String, Integer> getCostMap() {
        Map<String, Integer> map = new LinkedHashMap<>();
        for (TransmuteEntry entry : registry.values()) {
            map.put(entry.itemId(), entry.xpCost());
        }
        return map;
    }

    /**
     * Heuristic XP cost estimation for items not in ConjureAction's table.
     * Uses rarity, stack size, durability, and food properties.
     */
    private static int estimateXpCost(ItemStack stack) {
        Item item = stack.getItem();
        String itemId = BuiltInRegistries.ITEM.getKey(item).toString();

        // Check ConjureAction's hardcoded table first via reflection-free approach:
        // just use a known baseline for vanilla namespace
        if (itemId.startsWith("minecraft:")) {
            return estimateVanillaCost(item, itemId);
        }

        // Modded item heuristic
        return estimateModdedCost(item, stack);
    }

    private static int estimateVanillaCost(Item item, String itemId) {
        int baseCost = 2;

        Rarity rarity = item.components().has(net.minecraft.core.component.DataComponents.RARITY)
                ? item.components().get(net.minecraft.core.component.DataComponents.RARITY)
                : Rarity.COMMON;

        baseCost = switch (rarity) {
            case COMMON -> 2;
            case UNCOMMON -> 5;
            case RARE -> 10;
            case EPIC -> 20;
            default -> 20;
        };

        if (item.getDefaultMaxStackSize() == 1) {
            baseCost = Math.max(baseCost, 8);
            int durability = item.components().has(net.minecraft.core.component.DataComponents.MAX_DAMAGE)
                    ? item.components().get(net.minecraft.core.component.DataComponents.MAX_DAMAGE) : 0;
            if (durability > 0) {
                if (durability > 1500) baseCost = Math.max(baseCost, 15);
                else if (durability > 500) baseCost = Math.max(baseCost, 10);
            }
        }

        if (item.components().has(net.minecraft.core.component.DataComponents.FOOD)) {
            baseCost = Math.max(1, baseCost / 2);
        }

        return baseCost;
    }

    private static int estimateModdedCost(Item item, ItemStack stack) {
        int baseCost = 5;

        Rarity rarity = item.components().has(net.minecraft.core.component.DataComponents.RARITY)
                ? item.components().get(net.minecraft.core.component.DataComponents.RARITY)
                : Rarity.COMMON;

        baseCost = switch (rarity) {
            case COMMON -> 3;
            case UNCOMMON -> 8;
            case RARE -> 15;
            case EPIC -> 30;
            default -> 30;
        };

        if (item.getDefaultMaxStackSize() == 1) {
            baseCost = Math.max(baseCost, 10);
            int durability = item.components().has(net.minecraft.core.component.DataComponents.MAX_DAMAGE)
                    ? item.components().get(net.minecraft.core.component.DataComponents.MAX_DAMAGE) : 0;
            if (durability > 0) {
                if (durability > 2000) baseCost = Math.max(baseCost, 25);
                else if (durability > 1000) baseCost = Math.max(baseCost, 18);
                else if (durability > 500) baseCost = Math.max(baseCost, 12);
            }
        }

        if (item.components().has(net.minecraft.core.component.DataComponents.FOOD)) {
            baseCost = Math.max(2, baseCost / 2);
        }

        return baseCost;
    }
}
