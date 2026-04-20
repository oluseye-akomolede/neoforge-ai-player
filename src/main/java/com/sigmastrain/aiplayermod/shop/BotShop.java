package com.sigmastrain.aiplayermod.shop;

import com.google.gson.*;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.Items;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class BotShop {
    private static final Map<String, ShopItem> catalog = new ConcurrentHashMap<>();
    private static Path configPath;
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    public static void init(Path serverDir) {
        configPath = serverDir.resolve("config").resolve("aiplayermod-shop.json");
        loadConfig();
    }

    public static void loadConfig() {
        catalog.clear();
        if (configPath == null || !Files.exists(configPath)) {
            AIPlayerMod.LOGGER.info("No shop config found at {}, starting with empty catalog", configPath);
            return;
        }
        try (Reader r = Files.newBufferedReader(configPath)) {
            JsonObject root = JsonParser.parseReader(r).getAsJsonObject();
            JsonArray items = root.getAsJsonArray("items");
            if (items == null) return;
            for (JsonElement el : items) {
                JsonObject obj = el.getAsJsonObject();
                String itemId = obj.get("item").getAsString();
                int price = obj.get("price").getAsInt();
                int maxPerPurchase = obj.has("max_per_purchase") ? obj.get("max_per_purchase").getAsInt() : 64;
                String category = obj.has("category") ? obj.get("category").getAsString() : "general";
                boolean enabled = !obj.has("enabled") || obj.get("enabled").getAsBoolean();

                Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
                if (item == Items.AIR) {
                    AIPlayerMod.LOGGER.warn("Shop config: unknown item '{}', skipping", itemId);
                    continue;
                }

                if (enabled) {
                    catalog.put(itemId, new ShopItem(itemId, price, maxPerPurchase, category));
                }
            }
            AIPlayerMod.LOGGER.info("Loaded {} shop items from config", catalog.size());
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Failed to load shop config", e);
        }
    }

    public static void saveConfig() {
        if (configPath == null) return;
        try {
            Files.createDirectories(configPath.getParent());
            JsonObject root = new JsonObject();
            JsonArray items = new JsonArray();
            for (ShopItem si : catalog.values()) {
                JsonObject obj = new JsonObject();
                obj.addProperty("item", si.itemId());
                obj.addProperty("price", si.price());
                obj.addProperty("max_per_purchase", si.maxPerPurchase());
                obj.addProperty("category", si.category());
                obj.addProperty("enabled", true);
                items.add(obj);
            }
            root.add("items", items);
            try (Writer w = Files.newBufferedWriter(configPath)) {
                GSON.toJson(root, w);
            }
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Failed to save shop config", e);
        }
    }

    public static ShopItem get(String itemId) {
        return catalog.get(itemId);
    }

    public static void add(String itemId, int price, int maxPerPurchase, String category) {
        catalog.put(itemId, new ShopItem(itemId, price, maxPerPurchase, category));
        saveConfig();
    }

    public static boolean remove(String itemId) {
        boolean removed = catalog.remove(itemId) != null;
        if (removed) saveConfig();
        return removed;
    }

    public static List<Map<String, Object>> listAll() {
        List<Map<String, Object>> result = new ArrayList<>();
        for (ShopItem si : catalog.values()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("item", si.itemId());
            m.put("price", si.price());
            m.put("max_per_purchase", si.maxPerPurchase());
            m.put("category", si.category());
            result.add(m);
        }
        result.sort(Comparator.comparing(m -> (String) m.get("category")));
        return result;
    }

    public static int size() {
        return catalog.size();
    }

    public record ShopItem(String itemId, int price, int maxPerPurchase, String category) {}
}
