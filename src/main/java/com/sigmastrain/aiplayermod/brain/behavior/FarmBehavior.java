package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.CropBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.*;

/**
 * Constructs a bordered farm, plants crops (transmuting seeds if needed),
 * accelerates growth with XP, and harvests.
 * Directive target = crop type (wheat, carrot, potato, beetroot).
 * Directive extra "material" = border block (default: cobblestone).
 */
public class FarmBehavior implements Behavior {
    private enum Phase {
        TILLING, PLANTING, GROWING, HARVESTING, COLLECTING
    }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String cropType;
    private CropInfo cropInfo;
    private BlockPos origin;

    private static final int FARM_SIZE = 9;
    private static final int TICK_INTERVAL = 3;
    private static final int GROW_DURATION = 100; // 5 seconds

    private List<BlockPos> farmlandPositions;
    private BlockPos waterPos;

    private int stepIndex;
    private int cooldown;
    private int growTicks;
    private int growXpSpent;
    private int cropsHarvested;

    private static final Map<String, CropInfo> CROP_MAP = Map.of(
            "wheat", new CropInfo("minecraft:wheat_seeds", "minecraft:wheat"),
            "carrot", new CropInfo("minecraft:carrot", "minecraft:carrots"),
            "potato", new CropInfo("minecraft:potato", "minecraft:potatoes"),
            "beetroot", new CropInfo("minecraft:beetroot_seeds", "minecraft:beetroots")
    );

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();

        cropType = normalizeCropType(directive.getTarget());
        cropInfo = CROP_MAP.get(cropType);
        if (cropInfo == null) {
            progress.setFailureReason("Unknown crop: " + cropType
                    + ". Available: wheat, carrot, potato, beetroot");
            return;
        }

        ServerPlayer player = bot.getPlayer();
        origin = player.blockPosition().relative(Direction.fromYRot(player.getYRot()), 3);

        computePositions();

        stepIndex = 0;
        cooldown = 0;
        growTicks = 0;
        growXpSpent = 0;
        cropsHarvested = 0;
        phase = Phase.TILLING;

        int plots = farmlandPositions.size();
        progress.logEvent("Farm " + cropType + ": " + plots + " plots");
        bot.systemChat("Building " + cropType + " farm (" + plots + " plots)", "aqua");
        AIPlayerMod.LOGGER.info("[{}] FARM {} at {} ({} plots)",
                player.getName().getString(), cropType, origin, plots);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (progress.toMap().containsKey("failure_reason")) return BehaviorResult.FAILED;

        return switch (phase) {
            case TILLING -> tickTilling(bot);
            case PLANTING -> tickPlanting(bot);
            case GROWING -> tickGrowing(bot);
            case HARVESTING -> tickHarvesting(bot);
            case COLLECTING -> tickCollecting(bot);
        };
    }

    private BehaviorResult tickTilling(BotPlayer bot) {
        if (cooldown > 0) { cooldown--; return BehaviorResult.RUNNING; }

        // Place water source first tick
        if (stepIndex == 0) {
            ServerPlayer player = bot.getPlayer();
            player.serverLevel().setBlock(waterPos, Blocks.WATER.defaultBlockState(), 3);
            progress.logEvent("Water placed");
        }

        if (stepIndex >= farmlandPositions.size()) {
            progress.logEvent("Tilling complete");
            stepIndex = 0;
            phase = Phase.PLANTING;
            return BehaviorResult.RUNNING;
        }

        ServerPlayer player = bot.getPlayer();
        BlockPos pos = farmlandPositions.get(stepIndex);
        player.serverLevel().setBlock(pos, Blocks.FARMLAND.defaultBlockState(), 3);
        bot.lookAt(pos.getX() + 0.5, pos.getY() + 0.5, pos.getZ() + 0.5);

        stepIndex++;
        cooldown = TICK_INTERVAL;
        progress.setPhase("tilling (" + stepIndex + "/" + farmlandPositions.size() + ")");
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickPlanting(BotPlayer bot) {
        if (cooldown > 0) { cooldown--; return BehaviorResult.RUNNING; }
        if (stepIndex >= farmlandPositions.size()) {
            progress.logEvent("Planted " + stepIndex + " crops");
            bot.systemChat("Planted " + stepIndex + " " + cropType, "green");
            growTicks = 0;
            phase = Phase.GROWING;
            return BehaviorResult.RUNNING;
        }

        ServerPlayer player = bot.getPlayer();
        BlockPos cropPos = farmlandPositions.get(stepIndex).above();

        Item seedItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(cropInfo.seedItemId));
        if (!consumeItem(player, seedItem)) {
            ensureXp(player, 1);
            player.giveExperienceLevels(-1);
            progress.increment("seeds_transmuted");
        }

        Block cropBlock = BuiltInRegistries.BLOCK.get(ResourceLocation.parse(cropInfo.blockId));
        player.serverLevel().setBlock(cropPos, cropBlock.defaultBlockState(), 3);
        bot.lookAt(cropPos.getX() + 0.5, cropPos.getY() + 0.5, cropPos.getZ() + 0.5);

        stepIndex++;
        cooldown = TICK_INTERVAL;
        progress.setPhase("planting (" + stepIndex + "/" + farmlandPositions.size() + ")");
        progress.increment("crops_planted");
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickGrowing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        growTicks++;

        progress.setPhase("growing (" + growTicks + "/" + GROW_DURATION + ")");

        if (growTicks % 10 == 0) {
            ensureXp(player, 1);
            player.giveExperienceLevels(-1);
            growXpSpent++;

            for (BlockPos farmland : farmlandPositions) {
                BlockPos cropPos = farmland.above();
                BlockState state = level.getBlockState(cropPos);
                if (state.getBlock() instanceof CropBlock crop && !crop.isMaxAge(state)) {
                    int newAge = Math.min(crop.getAge(state) + 2, crop.getMaxAge());
                    level.setBlock(cropPos, crop.getStateForAge(newAge), 3);
                }
            }

            Vec3 center = Vec3.atCenterOf(origin.offset(FARM_SIZE / 2, 0, FARM_SIZE / 2));
            level.sendParticles(ParticleTypes.HAPPY_VILLAGER,
                    center.x, center.y + 1.0, center.z,
                    8, FARM_SIZE / 2.0, 0.5, FARM_SIZE / 2.0, 0.0);
        }

        if (growTicks >= GROW_DURATION) {
            progress.logEvent("Growth complete (cost " + growXpSpent + " XP)");
            bot.systemChat("Crops grown (" + growXpSpent + " XP)", "green");
            stepIndex = 0;
            phase = Phase.HARVESTING;
        }

        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickHarvesting(BotPlayer bot) {
        if (cooldown > 0) { cooldown--; return BehaviorResult.RUNNING; }
        if (stepIndex >= farmlandPositions.size()) {
            progress.logEvent("Harvested " + cropsHarvested + " crops");
            phase = Phase.COLLECTING;
            return BehaviorResult.RUNNING;
        }

        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockPos cropPos = farmlandPositions.get(stepIndex).above();

        BlockState state = level.getBlockState(cropPos);
        if (state.getBlock() instanceof CropBlock crop && crop.isMaxAge(state)) {
            level.destroyBlock(cropPos, true, player);
            cropsHarvested++;
            progress.increment("crops_harvested");
        }

        stepIndex++;
        cooldown = TICK_INTERVAL;
        progress.setPhase("harvesting (" + stepIndex + "/" + farmlandPositions.size() + ")");
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCollecting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        AABB box = new AABB(
                origin.getX() - 1, origin.getY() - 2, origin.getZ() - 1,
                origin.getX() + FARM_SIZE + 1, origin.getY() + 3, origin.getZ() + FARM_SIZE + 1);

        for (var entity : player.level().getEntities(player, box)) {
            if (entity instanceof ItemEntity item && item.isAlive()) {
                ItemStack stack = item.getItem();
                if (player.getInventory().add(stack.copy())) {
                    progress.increment("items_collected", stack.getCount());
                    item.discard();
                }
            }
        }

        progress.logEvent("Farm complete: " + cropsHarvested + " " + cropType + " harvested");
        bot.systemChat("Farm done: " + cropsHarvested + " " + cropType, "green");
        return BehaviorResult.SUCCESS;
    }

    private void computePositions() {
        farmlandPositions = new ArrayList<>();

        int center = FARM_SIZE / 2;
        waterPos = origin.offset(center, -1, center);
        for (int x = 0; x < FARM_SIZE; x++) {
            for (int z = 0; z < FARM_SIZE; z++) {
                if (x == center && z == center) continue;
                farmlandPositions.add(origin.offset(x, -1, z));
            }
        }
    }

    private static String normalizeCropType(String raw) {
        if (raw == null) return "wheat";
        String t = raw.toLowerCase();
        if (t.startsWith("minecraft:")) t = t.substring(10);
        if (t.equals("wheat_seeds")) return "wheat";
        if (t.equals("beetroot_seeds")) return "beetroot";
        if (t.equals("carrots")) return "carrot";
        if (t.equals("potatoes")) return "potato";
        if (t.endsWith("s") && !CROP_MAP.containsKey(t)) {
            String singular = t.substring(0, t.length() - 1);
            if (CROP_MAP.containsKey(singular)) return singular;
        }
        return t;
    }

    private boolean consumeItem(ServerPlayer player, Item item) {
        for (int i = 0; i < 36; i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty() && s.is(item)) {
                s.shrink(1);
                return true;
            }
        }
        return false;
    }

    private static void ensureXp(ServerPlayer player, int levels) {
        if (player.experienceLevel < levels) {
            player.giveExperienceLevels(levels - player.experienceLevel);
        }
    }

    @Override
    public String describeState() {
        return "Farm " + cropType + " [" + phase.name().toLowerCase() + "]";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}

    private record CropInfo(String seedItemId, String blockId) {}
}
