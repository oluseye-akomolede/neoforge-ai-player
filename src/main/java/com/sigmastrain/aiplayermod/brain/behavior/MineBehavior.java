package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.*;

/**
 * L1 Mine behavior with escalating search radius and channeling fallback.
 *
 * Escalation chain:
 *   search(64) → search(128) → search(256) → search(512) → search(1024) → channel items
 */
public class MineBehavior implements Behavior {
    private enum Phase {
        SEARCHING, EQUIPPING, PATHING, MINING, COLLECTING, COOLDOWN, CHANNELING
    }

    private final ProgressReport progress = new ProgressReport();
    private Directive directive;
    private Phase phase;

    private String targetBlock;
    private int targetCount;
    private int maxRadius;
    private BlockPos targetPos;
    private int breakProgress;
    private int collectTicks;
    private int cooldownTicks;
    private int totalMined;

    // Escalating search
    private static final int[] SEARCH_RADII = {64, 128, 256, 512, 1024};
    private int radiusIndex;

    // Channeling state
    private int channelTicks;
    private int channelTotal;
    private int channelXpCost;
    private String channelItemId;

    // Pre-check
    private boolean preCheckPassed;


    private static final int COLLECT_TICKS = 30;
    private static final int COOLDOWN_TICKS = 5;
    private static final double MINE_REACH = 4.5;
    private static final int TICKS_PER_LEVEL = 5;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        this.directive = directive;
        this.targetBlock = directive.getTarget();
        this.targetCount = directive.getCount() > 0 ? directive.getCount() : 1;
        this.maxRadius = directive.getRadius();
        this.totalMined = 0;
        this.radiusIndex = 0;
        progress.reset();

        // Inventory pre-check: skip mining if we already have enough of the drop item
        String dropId = resolveDropItem(targetBlock);
        if (dropId != null) {
            ServerPlayer player = bot.getPlayer();
            Item dropItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(dropId));
            if (dropItem != Items.AIR) {
                int owned = countInInventory(player, dropItem);
                if (owned >= targetCount) {
                    progress.logEvent("Already have " + owned + "x " + dropId + " (need " + targetCount + ")");
                    bot.systemChat("Already have " + owned + "x " + dropId, "green");
                    this.preCheckPassed = true;
                    return;
                }
            }
        }

        enterPhase(Phase.SEARCHING);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (preCheckPassed) {
            return BehaviorResult.SUCCESS;
        }
        if (totalMined >= targetCount) {
            progress.logEvent("Target count reached: " + totalMined);
            return BehaviorResult.SUCCESS;
        }

        return switch (phase) {
            case SEARCHING -> tickSearching(bot);
            case EQUIPPING -> tickEquipping(bot);
            case PATHING -> tickPathing(bot);
            case MINING -> tickMining(bot);
            case COLLECTING -> tickCollecting(bot);
            case COOLDOWN -> tickCooldown(bot);
            case CHANNELING -> tickChanneling(bot);
        };
    }

    private BehaviorResult tickSearching(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockPos center = player.blockPosition();
        String search = targetBlock.toLowerCase();

        int radius = SEARCH_RADII[Math.min(radiusIndex, SEARCH_RADII.length - 1)];
        radius = Math.min(radius, maxRadius);

        BlockPos nearest = findBlock(level, center, search, radius);

        if (nearest == null) {
            radiusIndex++;
            int nextRadius = radiusIndex < SEARCH_RADII.length
                    ? Math.min(SEARCH_RADII[radiusIndex], maxRadius)
                    : maxRadius;

            if (radiusIndex >= SEARCH_RADII.length || nextRadius <= radius) {
                // Exhausted all radii — fall back to channeling
                progress.logEvent("Could not find " + targetBlock + " within " + radius + " blocks, channeling");
                bot.systemChat("Channeling " + targetBlock + " (not found in " + radius + "b)", "light_purple");
                return startChanneling(bot);
            }

            progress.logEvent("Expanding search to " + nextRadius + " blocks");
            return BehaviorResult.RUNNING;
        }

        radiusIndex = 0; // Reset for next search cycle
        targetPos = nearest;
        progress.logEvent("Found " + targetBlock + " at " + nearest.toShortString());
        enterPhase(Phase.EQUIPPING);
        return BehaviorResult.RUNNING;
    }

    private BlockPos findBlock(ServerLevel level, BlockPos center, String search, int radius) {
        BlockPos nearest = null;
        double nearestDist = Double.MAX_VALUE;

        // Build variant match terms for ores (e.g. "allthemodium_ore" also matches "allthemodium_slate_ore")
        String searchBase = search.contains(":") ? search.substring(search.indexOf(':') + 1) : search;
        String oreBase = null;
        if (searchBase.endsWith("_ore")) {
            oreBase = searchBase.substring(0, searchBase.length() - 4);
        }

        for (int r = 1; r <= radius; r += (r < 64 ? 1 : 2)) {
            for (int x = -r; x <= r; x++) {
                for (int y = -r; y <= r; y++) {
                    for (int z = -r; z <= r; z++) {
                        if (Math.abs(x) != r && Math.abs(y) != r && Math.abs(z) != r) continue;
                        BlockPos pos = center.offset(x, y, z);
                        if (pos.getY() < level.getMinBuildHeight() || pos.getY() > level.getMaxBuildHeight())
                            continue;
                        BlockState state = level.getBlockState(pos);
                        if (state.isAir()) continue;
                        String id = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
                        if (matchesBlock(id, search, searchBase, oreBase)) {
                            double dist = center.distSqr(pos);
                            if (dist < nearestDist) {
                                nearestDist = dist;
                                nearest = pos;
                            }
                        }
                    }
                }
            }
            if (nearest != null) break;
        }
        return nearest;
    }

    private static boolean matchesBlock(String blockId, String search, String searchBase, String oreBase) {
        if (blockId.contains(search)) return true;
        if (blockId.contains(searchBase)) return true;
        // For ore variants: "iron_ore" matches "deepslate_iron_ore", "allthemodium_ore" matches "allthemodium_slate_ore"
        if (oreBase != null && blockId.contains(oreBase) && blockId.contains("ore")) return true;
        return false;
    }

    private BehaviorResult startChanneling(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        int remaining = targetCount - totalMined;

        // Resolve what item the block drops
        channelItemId = resolveDropItem(targetBlock);
        if (channelItemId == null) {
            progress.setFailureReason("Cannot channel: unknown drop for " + targetBlock);
            return BehaviorResult.FAILED;
        }

        // Calculate XP cost using ConjureAction cost table logic
        channelXpCost = getConjureCost(channelItemId) * remaining;

        // Auto-meditate if not enough XP
        if (player.experienceLevel < channelXpCost) {
            int needed = channelXpCost - player.experienceLevel;
            player.giveExperienceLevels(needed);
            progress.logEvent("Meditated for " + needed + " XP levels");
        }

        channelTotal = remaining;
        channelTicks = Math.max(5, channelXpCost * TICKS_PER_LEVEL);
        enterPhase(Phase.CHANNELING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickChanneling(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();

        // Particles every 3 ticks
        if (channelTicks % 3 == 0) {
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 1.0, pos.z, 2, 0.8, 0.5, 0.8, 0.2);
            level.sendParticles(ParticleTypes.END_ROD,
                    pos.x, pos.y + 1.5, pos.z, 1, 0.3, 0.3, 0.3, 0.02);
        }

        channelTicks--;
        if (channelTicks > 0) return BehaviorResult.RUNNING;

        // Complete channeling
        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(channelItemId));
        if (item == Items.AIR) {
            progress.setFailureReason("Channel failed: invalid item " + channelItemId);
            return BehaviorResult.FAILED;
        }

        ItemStack stack = new ItemStack(item, channelTotal);
        player.giveExperienceLevels(-channelXpCost);
        player.getInventory().add(stack);
        totalMined += channelTotal;
        progress.increment("items_channeled", channelTotal);
        progress.logEvent("Channeled " + channelTotal + "x " + channelItemId + " (cost " + channelXpCost + " levels)");

        level.sendParticles(ParticleTypes.END_ROD,
                pos.x, pos.y + 1.0, pos.z, 15, 0.5, 0.8, 0.5, 0.1);
        level.playSound(null, player.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.7f, 1.2f);

        bot.systemChat("Channeled " + channelTotal + "x " + channelItemId, "light_purple");
        return BehaviorResult.SUCCESS;
    }

    private BehaviorResult tickEquipping(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockState state = level.getBlockState(targetPos);

        if (state.isAir()) {
            enterPhase(Phase.SEARCHING);
            return BehaviorResult.RUNNING;
        }

        int bestSlot = -1;
        float bestSpeed = 1.0f;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            float speed = stack.getDestroySpeed(state);
            if (speed > bestSpeed) {
                bestSpeed = speed;
                bestSlot = i;
            }
        }

        if (bestSlot >= 0) {
            if (bestSlot >= 9) {
                bot.swapSlot(bestSlot, player.getInventory().selected);
            } else {
                player.getInventory().selected = bestSlot;
            }
        }

        enterPhase(Phase.PATHING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickPathing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        if (level.getBlockState(targetPos).isAir()) {
            enterPhase(Phase.SEARCHING);
            return BehaviorResult.RUNNING;
        }

        Vec3 target = Vec3.atCenterOf(targetPos);
        double dist = player.position().distanceTo(target);

        if (dist <= MINE_REACH) {
            enterPhase(Phase.MINING);
            breakProgress = 0;
            return BehaviorResult.RUNNING;
        }

        // Teleport to adjacent position for distant blocks
        BlockPos adjacent = findStandingPos(level, targetPos);
        player.teleportTo(adjacent.getX() + 0.5, adjacent.getY(), adjacent.getZ() + 0.5);
        bot.lookAt(targetPos.getX() + 0.5, targetPos.getY() + 0.5, targetPos.getZ() + 0.5);
        enterPhase(Phase.MINING);
        breakProgress = 0;
        return BehaviorResult.RUNNING;
    }

    private BlockPos findStandingPos(ServerLevel level, BlockPos target) {
        // Try adjacent positions for existing air pockets
        BlockPos[] offsets = {
            target.north(), target.south(), target.east(), target.west(),
            target.above().north(), target.above().south(), target.above().east(), target.above().west(),
            target.above(2),
        };
        for (BlockPos pos : offsets) {
            if (level.getBlockState(pos).isAir() && level.getBlockState(pos.above()).isAir()) {
                return pos;
            }
        }
        // Underground ore — carve a 2-high standing pocket adjacent to the target
        BlockPos stand = target.above();
        level.destroyBlock(stand, false);
        level.destroyBlock(stand.above(), false);
        return stand;
    }

    private BehaviorResult tickMining(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockState state = level.getBlockState(targetPos);

        if (state.isAir()) {
            totalMined++;
            progress.increment("blocks_mined");
            progress.logEvent("Mined block at " + targetPos.toShortString() + " (" + totalMined + "/" + targetCount + ")");
            enterPhase(Phase.COLLECTING);
            collectTicks = 0;
            return BehaviorResult.RUNNING;
        }

        bot.lookAt(targetPos.getX() + 0.5, targetPos.getY() + 0.5, targetPos.getZ() + 0.5);

        float hardness = state.getDestroySpeed(level, targetPos);
        if (hardness < 0) {
            progress.logEvent("Unbreakable block at " + targetPos.toShortString());
            enterPhase(Phase.SEARCHING);
            return BehaviorResult.RUNNING;
        }

        float speed = player.getMainHandItem().getDestroySpeed(state);
        float progressPerTick = speed / hardness / 30.0f;
        breakProgress++;

        if (breakProgress * progressPerTick >= 1.0f || hardness == 0) {
            net.minecraft.world.level.block.entity.BlockEntity be = state.hasBlockEntity() ? level.getBlockEntity(targetPos) : null;
            Block.dropResources(state, level, targetPos, be, player, player.getMainHandItem());
            level.destroyBlock(targetPos, false, player);
        }

        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCollecting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        collectTicks++;

        AABB collectBox = player.getBoundingBox().inflate(3.0);
        for (var entity : player.level().getEntities(player, collectBox)) {
            if (entity instanceof ItemEntity item && item.isAlive()) {
                ItemStack stack = item.getItem();
                if (player.getInventory().add(stack.copy())) {
                    progress.increment("items_collected", stack.getCount());
                    item.discard();
                }
            }
        }

        if (collectTicks >= COLLECT_TICKS) {
            enterPhase(Phase.COOLDOWN);
            cooldownTicks = 0;
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCooldown(BotPlayer bot) {
        cooldownTicks++;
        if (cooldownTicks >= COOLDOWN_TICKS) {
            enterPhase(Phase.SEARCHING);
        }
        return BehaviorResult.RUNNING;
    }

    private int countInInventory(ServerPlayer player, Item item) {
        int total = 0;
        for (int i = 0; i < 36; i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty() && s.is(item)) {
                total += s.getCount();
            }
        }
        return total;
    }

    /**
     * Resolve what item a block drops (simplified mapping for common ores/blocks).
     */
    private String resolveDropItem(String blockTarget) {
        String t = blockTarget.toLowerCase();
        if (t.contains("iron_ore")) return "minecraft:raw_iron";
        if (t.contains("gold_ore")) return "minecraft:raw_gold";
        if (t.contains("copper_ore")) return "minecraft:raw_copper";
        if (t.contains("coal_ore")) return "minecraft:coal";
        if (t.contains("diamond_ore")) return "minecraft:diamond";
        if (t.contains("emerald_ore")) return "minecraft:emerald";
        if (t.contains("lapis_ore")) return "minecraft:lapis_lazuli";
        if (t.contains("redstone_ore")) return "minecraft:redstone";
        if (t.contains("quartz_ore")) return "minecraft:quartz";
        if (t.contains("ancient_debris")) return "minecraft:ancient_debris";
        if (t.contains("log")) return "minecraft:" + (t.contains(":") ? t.split(":")[1] : "oak_log");
        if (t.contains("cobblestone")) return "minecraft:cobblestone";
        if (t.contains("stone")) return "minecraft:cobblestone";
        if (t.contains("sand")) return "minecraft:sand";
        if (t.contains("gravel")) return "minecraft:gravel";
        if (t.contains("dirt")) return "minecraft:dirt";
        if (t.contains("clay")) return "minecraft:clay_ball";
        if (t.contains("obsidian")) return "minecraft:obsidian";
        // Generic fallback: try minecraft:<target> as item
        String id = t.contains(":") ? t : "minecraft:" + t;
        try {
            Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(id));
            if (item != Items.AIR) return id;
        } catch (Exception ignored) {}
        return null;
    }

    private int getConjureCost(String itemId) {
        // Mirror ConjureAction cost table
        return switch (itemId) {
            case "minecraft:dirt", "minecraft:cobblestone", "minecraft:sand",
                 "minecraft:gravel", "minecraft:clay_ball", "minecraft:oak_log",
                 "minecraft:spruce_log", "minecraft:birch_log", "minecraft:jungle_log",
                 "minecraft:acacia_log", "minecraft:dark_oak_log" -> 1;
            case "minecraft:coal", "minecraft:raw_copper" -> 2;
            case "minecraft:raw_iron", "minecraft:raw_gold", "minecraft:lapis_lazuli",
                 "minecraft:redstone", "minecraft:quartz" -> 3;
            case "minecraft:emerald" -> 5;
            case "minecraft:diamond" -> 15;
            case "minecraft:ancient_debris" -> 25;
            case "minecraft:obsidian" -> 4;
            default -> 8;
        };
    }

    private void enterPhase(Phase newPhase) {
        this.phase = newPhase;
        progress.setPhase(newPhase.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case SEARCHING -> "Searching for " + targetBlock + " (radius " + SEARCH_RADII[Math.min(radiusIndex, SEARCH_RADII.length - 1)] + ")";
            case EQUIPPING -> "Equipping tool";
            case PATHING -> "Moving to " + (targetPos != null ? targetPos.toShortString() : "target");
            case MINING -> "Mining at " + (targetPos != null ? targetPos.toShortString() : "target");
            case COLLECTING -> "Collecting drops";
            case COOLDOWN -> "Cooldown";
            case CHANNELING -> "Channeling " + channelItemId + " (" + channelTicks / 20 + "s)";
        };
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {
        targetPos = null;
        phase = Phase.SEARCHING;
    }
}
