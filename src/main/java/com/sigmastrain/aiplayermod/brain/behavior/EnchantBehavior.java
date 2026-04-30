package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.shop.EnchantmentRegistry;
import net.minecraft.core.Holder;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.util.RandomSource;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.enchantment.Enchantment;
import net.minecraft.world.item.enchantment.EnchantmentHelper;
import net.minecraft.world.item.enchantment.EnchantmentInstance;
import net.minecraft.world.phys.Vec3;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Stream;

/**
 * Deterministic enchanting — bots can apply specific enchantments by name.
 * Falls back to random enchantment selection if no specific enchantment is given.
 * Auto-meditates for XP if the bot doesn't have enough.
 *
 * Directive target formats:
 *   "sharpness 5"                → find enchantable weapon, apply sharpness 5
 *   "sharpness 5 on iron_sword"  → find iron_sword, apply sharpness 5
 *   "iron_sword"                 → find iron_sword, apply random enchantment (option tier)
 *   ""                           → find any enchantable item, apply random enchantment
 *
 * Extra params:
 *   enchantment: "minecraft:sharpness" — explicit enchantment ID
 *   level: "3" — enchantment level
 *   option: "0"|"1"|"2" — random tier (basic/mid/max), used when no specific enchantment
 */
public class EnchantBehavior implements Behavior {
    private enum Phase { VALIDATE, MEDITATING, ENCHANTING }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String targetItem;
    private String requestedEnchantment;
    private int requestedLevel;
    private int option;
    private int itemSlot = -1;
    private int xpCost;
    private int enchantTicks;
    private int meditateTarget;
    private int meditateTicks;
    private int meditateLevelsGained;

    private Holder<Enchantment> resolvedEnchantment;

    private static final int ENCHANT_DURATION = 20;
    private static final int TICKS_PER_LEVEL = 1;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        Map<String, String> extra = directive.getExtra();

        this.requestedEnchantment = extra.getOrDefault("enchantment", "");
        this.requestedLevel = parseIntOr(extra.get("level"), -1);
        this.option = parseIntOr(extra.get("option"), 2);
        this.option = Math.max(0, Math.min(2, this.option));

        String rawTarget = directive.getTarget();
        parseTarget(rawTarget);

        enterPhase(Phase.VALIDATE);
    }

    private void parseTarget(String raw) {
        if (raw == null || raw.isEmpty()) {
            targetItem = "";
            return;
        }

        if (requestedEnchantment != null && !requestedEnchantment.isEmpty()) {
            targetItem = raw;
            return;
        }

        // "sharpness 5 on iron_sword" or "sharpness 5"
        String lower = raw.toLowerCase().trim();
        if (lower.contains(" on ")) {
            String[] parts = lower.split("\\s+on\\s+", 2);
            parseEnchantmentFromText(parts[0].trim());
            targetItem = parts[1].trim();
        } else {
            // Try to parse as "enchantment_name level" first
            if (parseEnchantmentFromText(lower)) {
                targetItem = "";
            } else {
                targetItem = raw;
            }
        }
    }

    private boolean parseEnchantmentFromText(String text) {
        // Try "enchantment_name N" pattern
        String[] words = text.split("\\s+");
        if (words.length >= 2) {
            String lastWord = words[words.length - 1];
            try {
                int level = Integer.parseInt(lastWord);
                String enchName = String.join("_", java.util.Arrays.copyOf(words, words.length - 1));
                if (!enchName.contains(":")) enchName = "minecraft:" + enchName;
                if (EnchantmentRegistry.isKnown(enchName)) {
                    requestedEnchantment = enchName;
                    requestedLevel = level;
                    return true;
                }
            } catch (NumberFormatException ignored) {}
        }

        // Try whole string as enchantment name
        String enchName = text.replace(" ", "_");
        if (!enchName.contains(":")) enchName = "minecraft:" + enchName;
        if (EnchantmentRegistry.isKnown(enchName)) {
            requestedEnchantment = enchName;
            if (requestedLevel < 0) requestedLevel = EnchantmentRegistry.getMaxLevel(enchName);
            return true;
        }

        return false;
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case VALIDATE -> tickValidate(bot);
            case MEDITATING -> tickMeditating(bot);
            case ENCHANTING -> tickEnchanting(bot);
        };
    }

    private BehaviorResult tickValidate(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        itemSlot = findItemSlot(player, targetItem);
        if (itemSlot < 0) {
            progress.setFailureReason("No enchantable item found" +
                    (targetItem.isEmpty() ? " in inventory" : " matching '" + targetItem + "'"));
            return BehaviorResult.FAILED;
        }

        String itemId = BuiltInRegistries.ITEM.getKey(player.getInventory().getItem(itemSlot).getItem()).toString();

        // Resolve specific enchantment if requested
        if (requestedEnchantment != null && !requestedEnchantment.isEmpty()) {
            if (!requestedEnchantment.contains(":"))
                requestedEnchantment = "minecraft:" + requestedEnchantment;

            Optional<Holder<Enchantment>> opt = EnchantmentRegistry.resolve(
                    requestedEnchantment, player.server);
            if (opt.isEmpty()) {
                progress.setFailureReason("Unknown enchantment: " + requestedEnchantment);
                return BehaviorResult.FAILED;
            }
            resolvedEnchantment = opt.get();

            int maxLevel = resolvedEnchantment.value().definition().maxLevel();
            if (requestedLevel < 0) requestedLevel = maxLevel;
            requestedLevel = Math.max(1, Math.min(requestedLevel, 255));

            xpCost = EnchantmentRegistry.getCostPerLevel(requestedEnchantment) * requestedLevel;
            progress.logEvent("Enchanting " + itemId + " with " + requestedEnchantment +
                    " " + requestedLevel + " (cost: " + xpCost + " XP)");
        } else {
            // Random enchantment mode
            resolvedEnchantment = null;
            RandomSource random = player.getRandom();
            int enchantLevel = switch (option) {
                case 0 -> 1 + random.nextInt(8);
                case 1 -> 9 + random.nextInt(12);
                default -> 21 + random.nextInt(10);
            };
            xpCost = enchantLevel;
            requestedLevel = enchantLevel;
            progress.logEvent("Random enchant " + itemId + " at level " + enchantLevel +
                    " (cost: " + xpCost + " XP)");
        }

        if (player.experienceLevel < xpCost) {
            meditateTarget = xpCost - player.experienceLevel;
            meditateTicks = 0;
            meditateLevelsGained = 0;
            progress.logEvent("Need " + meditateTarget + " more XP levels, meditating");
            bot.systemChat("Meditating for " + meditateTarget + " XP levels...", "light_purple");
            enterPhase(Phase.MEDITATING);
            return BehaviorResult.RUNNING;
        }

        enchantTicks = 0;
        enterPhase(Phase.ENCHANTING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickMeditating(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        meditateTicks++;

        if (meditateTicks % 4 == 0) {
            Vec3 pos = player.position();
            level.sendParticles(ParticleTypes.ENCHANT,
                    pos.x, pos.y + 1.5, pos.z, 3, 0.5, 0.5, 0.5, 0.1);
        }

        if (meditateTicks % TICKS_PER_LEVEL == 0) {
            player.giveExperienceLevels(1);
            meditateLevelsGained++;
            progress.increment("xp_levels_gained");

            if (meditateLevelsGained >= meditateTarget) {
                progress.logEvent("Meditation complete: gained " + meditateLevelsGained + " levels");
                enchantTicks = 0;
                enterPhase(Phase.ENCHANTING);
            }
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickEnchanting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();
        enchantTicks++;

        if (enchantTicks % 3 == 0) {
            level.sendParticles(ParticleTypes.ENCHANT,
                    pos.x, pos.y + 1.0, pos.z, 5, 0.8, 1.0, 0.8, 0.3);
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 0.5, pos.z, 3, 0.5, 0.5, 0.5, 0.2);
        }

        if (enchantTicks < ENCHANT_DURATION) return BehaviorResult.RUNNING;

        ItemStack item = player.getInventory().getItem(itemSlot);
        if (item.isEmpty()) {
            progress.setFailureReason("Item disappeared from slot " + itemSlot);
            return BehaviorResult.FAILED;
        }

        player.giveExperienceLevels(-xpCost);

        String itemId = BuiltInRegistries.ITEM.getKey(item.getItem()).toString();
        String enchantDesc;

        if (resolvedEnchantment != null) {
            // Deterministic: apply the exact requested enchantment
            item.enchant(resolvedEnchantment, requestedLevel);
            String enchName = resolvedEnchantment.unwrapKey()
                    .map(k -> k.location().getPath()).orElse("unknown");
            enchantDesc = enchName + " " + requestedLevel;
        } else {
            // Random: use vanilla selection
            RandomSource random = player.getRandom();
            Stream<Holder<Enchantment>> enchantmentStream =
                    level.registryAccess().lookupOrThrow(Registries.ENCHANTMENT)
                            .listElements().map(ref -> (Holder<Enchantment>) ref);
            List<EnchantmentInstance> enchants =
                    EnchantmentHelper.selectEnchantment(random, item, requestedLevel, enchantmentStream);

            if (enchants.isEmpty()) {
                player.giveExperienceLevels(xpCost);
                progress.setFailureReason("No compatible enchantments for this item at level " + requestedLevel);
                return BehaviorResult.FAILED;
            }

            for (var inst : enchants) {
                item.enchant(inst.enchantment, inst.level);
            }

            StringBuilder sb = new StringBuilder();
            for (var inst : enchants) {
                if (!sb.isEmpty()) sb.append(", ");
                String name = inst.enchantment.unwrapKey()
                        .map(k -> k.location().getPath()).orElse("unknown");
                sb.append(name).append(" ").append(inst.level);
            }
            enchantDesc = sb.toString();
        }

        // Effects
        level.sendParticles(ParticleTypes.END_ROD,
                pos.x, pos.y + 1.5, pos.z, 20, 0.5, 1.0, 0.5, 0.15);
        level.playSound(null, player.blockPosition(),
                SoundEvents.ENCHANTMENT_TABLE_USE, SoundSource.PLAYERS, 1.0f, 1.0f);

        progress.increment("items_enchanted");
        progress.logEvent("Enchanted " + itemId + ": " + enchantDesc);
        bot.systemChat("Enchanted " + itemId + " with " + enchantDesc, "light_purple");
        AIPlayerMod.LOGGER.info("[{}] Enchanted: {} -> {} (cost {} XP)",
                player.getName().getString(), itemId, enchantDesc, xpCost);

        return BehaviorResult.SUCCESS;
    }

    private int findItemSlot(ServerPlayer player, String search) {
        if (search != null && !search.isEmpty()) {
            // Try as slot number
            try {
                int slot = Integer.parseInt(search);
                ItemStack stack = player.getInventory().getItem(slot);
                if (!stack.isEmpty()) return slot;
            } catch (NumberFormatException ignored) {}

            // Search by item name
            String s = search.toLowerCase();
            for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
                ItemStack stack = player.getInventory().getItem(i);
                if (stack.isEmpty()) continue;
                String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
                if (id.contains(s)) return i;
            }
        }

        // Fallback: find any enchantable item
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty() && stack.isEnchantable()) return i;
        }
        return -1;
    }

    private static int parseIntOr(String s, int fallback) {
        if (s == null || s.isEmpty()) return fallback;
        try { return Integer.parseInt(s); }
        catch (NumberFormatException e) { return fallback; }
    }

    private void enterPhase(Phase p) {
        this.phase = p;
        progress.setPhase(p.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case VALIDATE -> "Preparing to enchant";
            case MEDITATING -> "Meditating for XP (" + meditateLevelsGained + "/" + meditateTarget + ")";
            case ENCHANTING -> "Channeling enchantment (" + enchantTicks + "/" + ENCHANT_DURATION + ")";
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
