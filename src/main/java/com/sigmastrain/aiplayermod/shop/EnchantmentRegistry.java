package com.sigmastrain.aiplayermod.shop;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.Holder;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.enchantment.Enchantment;
import net.minecraft.world.item.enchantment.EnchantmentHelper;
import net.minecraft.world.item.enchantment.ItemEnchantments;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Server-wide registry of known enchantments and their XP costs.
 * All vanilla enchantments are auto-registered on startup.
 * Modded enchantments are discovered when bots encounter enchanted items.
 */
public class EnchantmentRegistry {
    private static final Map<String, EnchantmentEntry> registry = new ConcurrentHashMap<>();

    public record EnchantmentEntry(
            String enchantmentId,
            int maxLevel,
            int xpCostPerLevel,
            String source
    ) {}

    public static void init(MinecraftServer server) {
        registry.clear();
        var lookup = server.registryAccess().lookupOrThrow(Registries.ENCHANTMENT);
        lookup.listElements().forEach(ref -> {
            String id = ref.key().location().toString();
            Enchantment ench = ref.value();
            int maxLevel = ench.definition().maxLevel();
            int costPerLevel = estimateCost(ench);
            registry.put(id, new EnchantmentEntry(id, maxLevel, costPerLevel, "vanilla"));
        });
        AIPlayerMod.LOGGER.info("Enchantment registry: loaded {} enchantments", registry.size());
    }

    public static void discoverFromItem(ItemStack stack, String source) {
        if (stack.isEmpty()) return;
        ItemEnchantments enchantments = stack.getEnchantments();
        if (enchantments.isEmpty()) return;

        enchantments.entrySet().forEach(entry -> {
            Holder<Enchantment> holder = entry.getKey();
            String id = holder.unwrapKey()
                    .map(k -> k.location().toString())
                    .orElse(null);
            if (id == null) return;
            if (registry.containsKey(id)) return;

            int maxLevel = holder.value().definition().maxLevel();
            int observedLevel = entry.getIntValue();
            maxLevel = Math.max(maxLevel, observedLevel);
            int costPerLevel = estimateCost(holder.value());
            registry.put(id, new EnchantmentEntry(id, maxLevel, costPerLevel, source));
            AIPlayerMod.LOGGER.info("Enchantment registry: discovered {} (max={}, cost={}/lvl, source={})",
                    id, maxLevel, costPerLevel, source);
        });
    }

    public static boolean isKnown(String enchantmentId) {
        return registry.containsKey(enchantmentId);
    }

    public static EnchantmentEntry get(String enchantmentId) {
        return registry.get(enchantmentId);
    }

    public static int getMaxLevel(String enchantmentId) {
        EnchantmentEntry entry = registry.get(enchantmentId);
        return entry != null ? entry.maxLevel() : -1;
    }

    public static int getCostPerLevel(String enchantmentId) {
        EnchantmentEntry entry = registry.get(enchantmentId);
        return entry != null ? entry.xpCostPerLevel() : 5;
    }

    public static int size() {
        return registry.size();
    }

    public static List<Map<String, Object>> listAll() {
        List<Map<String, Object>> result = new ArrayList<>();
        for (EnchantmentEntry entry : registry.values()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", entry.enchantmentId());
            m.put("max_level", entry.maxLevel());
            m.put("xp_cost_per_level", entry.xpCostPerLevel());
            m.put("source", entry.source());
            result.add(m);
        }
        result.sort(Comparator.comparing(m -> (String) m.get("id")));
        return result;
    }

    public static Optional<Holder<Enchantment>> resolve(String enchantmentId, MinecraftServer server) {
        if (!enchantmentId.contains(":")) {
            enchantmentId = "minecraft:" + enchantmentId;
        }
        var key = ResourceKey.create(Registries.ENCHANTMENT, ResourceLocation.parse(enchantmentId));
        return server.registryAccess().lookupOrThrow(Registries.ENCHANTMENT)
                .get(key).map(ref -> (Holder<Enchantment>) ref);
    }

    private static int estimateCost(Enchantment enchantment) {
        int weight = enchantment.definition().weight();
        int maxLevel = enchantment.definition().maxLevel();
        if (weight >= 10) return 3;
        if (weight >= 5) return 5;
        if (weight >= 2) return 8;
        return 12;
    }
}
