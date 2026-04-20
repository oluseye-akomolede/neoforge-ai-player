package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.server.level.ServerPlayer;

import java.lang.reflect.Method;
import java.util.Map;

public class PmmoCompat {
    private static boolean checked = false;
    private static boolean available = false;
    private static Method setLevelMethod;
    private static Method getAllLevelsMethod;

    private static final Map<String, Integer> SKILL_LEVELS = Map.ofEntries(
            Map.entry("combat", 250),
            Map.entry("magic", 30),
            Map.entry("mining", 350),
            Map.entry("building", 350),
            Map.entry("crafting", 350),
            Map.entry("farming", 350),
            Map.entry("agility", 350),
            Map.entry("endurance", 350),
            Map.entry("woodcutting", 350),
            Map.entry("fishing", 350),
            Map.entry("swimming", 350),
            Map.entry("flying", 350),
            Map.entry("sailing", 350),
            Map.entry("taming", 350),
            Map.entry("hunter", 350),
            Map.entry("excavating", 350),
            Map.entry("smithing", 350),
            Map.entry("cooking", 350),
            Map.entry("alchemy", 350),
            Map.entry("engineering", 350),
            Map.entry("archery", 350),
            Map.entry("slayer", 350)
    );

    private static void resolve() {
        if (checked) return;
        checked = true;
        try {
            Class<?> apiUtils = Class.forName("harmonised.pmmo.api.APIUtils");
            setLevelMethod = apiUtils.getMethod("setLevel", String.class,
                    net.minecraft.world.entity.player.Player.class, int.class);
            getAllLevelsMethod = apiUtils.getMethod("getAllLevels",
                    net.minecraft.world.entity.player.Player.class);
            available = true;
            AIPlayerMod.LOGGER.info("ProjectMMO detected — bot skill levels will be configured");
        } catch (ClassNotFoundException e) {
            AIPlayerMod.LOGGER.info("ProjectMMO not found — skipping skill setup");
        } catch (Exception e) {
            AIPlayerMod.LOGGER.warn("ProjectMMO detected but API reflection failed: {}", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    public static void setupBotSkills(ServerPlayer player) {
        resolve();
        if (!available) return;

        try {
            Map<String, Long> currentLevels = (Map<String, Long>) getAllLevelsMethod.invoke(null, player);

            for (var entry : SKILL_LEVELS.entrySet()) {
                try {
                    setLevelMethod.invoke(null, entry.getKey(), player, entry.getValue());
                } catch (Exception e) {
                    AIPlayerMod.LOGGER.debug("Could not set PMMO skill {}: {}", entry.getKey(), e.getMessage());
                }
            }

            // Also set any skills that exist in-game but aren't in our default map
            if (currentLevels != null) {
                for (String skill : currentLevels.keySet()) {
                    if (!SKILL_LEVELS.containsKey(skill)) {
                        try {
                            int level = skill.equalsIgnoreCase("combat") ? 250
                                    : skill.equalsIgnoreCase("magic") ? 30
                                    : 350;
                            setLevelMethod.invoke(null, skill, player, level);
                        } catch (Exception e) {
                            AIPlayerMod.LOGGER.debug("Could not set PMMO skill {}: {}", skill, e.getMessage());
                        }
                    }
                }
            }

            AIPlayerMod.LOGGER.info("Set PMMO skills for bot {} (combat=250, magic=30, others=350)",
                    player.getName().getString());
        } catch (Exception e) {
            AIPlayerMod.LOGGER.warn("Failed to set PMMO skills for {}: {}", player.getName().getString(), e.getMessage());
        }
    }
}
