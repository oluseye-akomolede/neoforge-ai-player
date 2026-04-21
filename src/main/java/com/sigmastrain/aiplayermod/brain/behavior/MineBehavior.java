package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.PickaxeItem;
import net.minecraft.world.item.AxeItem;
import net.minecraft.world.item.ShovelItem;
import net.minecraft.world.item.SwordItem;
import net.minecraft.world.item.DiggerItem;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.*;

public class MineBehavior implements Behavior {
    private enum Phase { SEARCHING, EQUIPPING, PATHING, MINING, COLLECTING, COOLDOWN }

    private final ProgressReport progress = new ProgressReport();
    private Directive directive;
    private Phase phase;

    private String targetBlock;
    private int targetCount;
    private int searchRadius;
    private BlockPos targetPos;
    private int breakProgress;
    private int collectTicks;
    private int cooldownTicks;
    private int searchFailures;
    private int totalMined;

    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;

    private static final int MAX_SEARCH_FAILURES = 5;
    private static final int COLLECT_TICKS = 30;
    private static final int COOLDOWN_TICKS = 5;
    private static final double MINE_REACH = 4.5;
    private static final double WALK_SPEED = 0.2;
    private static final double SPRINT_SPEED = 0.4;
    private static final double FLY_SPEED = 0.8;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        this.directive = directive;
        this.targetBlock = directive.getTarget();
        this.targetCount = directive.getCount() > 0 ? directive.getCount() : Integer.MAX_VALUE;
        this.searchRadius = directive.getRadius();
        this.totalMined = 0;
        this.searchFailures = 0;
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        progress.reset();
        enterPhase(Phase.SEARCHING);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
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
        };
    }

    private BehaviorResult tickSearching(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockPos center = player.blockPosition();
        String search = targetBlock.toLowerCase();

        BlockPos nearest = null;
        double nearestDist = Double.MAX_VALUE;

        for (int r = 1; r <= searchRadius; r++) {
            for (int x = -r; x <= r; x++) {
                for (int y = -r; y <= r; y++) {
                    for (int z = -r; z <= r; z++) {
                        if (Math.abs(x) != r && Math.abs(y) != r && Math.abs(z) != r) continue;
                        BlockPos pos = center.offset(x, y, z);
                        BlockState state = level.getBlockState(pos);
                        if (state.isAir()) continue;
                        String id = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
                        String name = state.getBlock().getName().getString().toLowerCase();
                        if (id.contains(search) || name.contains(search)) {
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

        if (nearest == null) {
            searchFailures++;
            progress.logEvent("No " + targetBlock + " found (attempt " + searchFailures + ")");
            if (searchFailures >= MAX_SEARCH_FAILURES) {
                progress.setFailureReason("Could not find " + targetBlock + " within " + searchRadius + " blocks");
                return BehaviorResult.FAILED;
            }
            return BehaviorResult.RUNNING;
        }

        searchFailures = 0;
        targetPos = nearest;
        progress.logEvent("Found " + targetBlock + " at " + nearest.toShortString());
        enterPhase(Phase.EQUIPPING);
        return BehaviorResult.RUNNING;
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
        for (int i = 0; i < 9; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            float speed = stack.getDestroySpeed(state);
            if (speed > bestSpeed) {
                bestSpeed = speed;
                bestSlot = i;
            }
        }
        for (int i = 9; i < player.getInventory().getContainerSize(); i++) {
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
                int hotbarSlot = player.getInventory().selected;
                bot.swapSlot(bestSlot, hotbarSlot);
            } else {
                player.getInventory().selected = bestSlot;
            }
        }

        enterPhase(Phase.PATHING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickPathing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Vec3 currentPos = player.position();
        Vec3 target = Vec3.atCenterOf(targetPos);
        double dist = currentPos.distanceTo(target);

        if (dist <= MINE_REACH) {
            enterPhase(Phase.MINING);
            breakProgress = 0;
            return BehaviorResult.RUNNING;
        }

        ServerLevel level = player.serverLevel();
        if (level.getBlockState(targetPos).isAir()) {
            enterPhase(Phase.SEARCHING);
            return BehaviorResult.RUNNING;
        }

        moveToward(bot, player, target, dist);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickMining(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockState state = level.getBlockState(targetPos);

        if (state.isAir()) {
            totalMined++;
            progress.increment("blocks_mined");
            progress.logEvent("Mined block at " + targetPos.toShortString() + " (" + totalMined + "/" + (targetCount == Integer.MAX_VALUE ? "∞" : targetCount) + ")");
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
            level.destroyBlock(targetPos, true, player);
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

    private void moveToward(BotPlayer bot, ServerPlayer player, Vec3 target, double dist) {
        Vec3 currentPos = player.position();

        double heightDiff = Math.abs(target.y - currentPos.y);
        if (heightDiff > 4.0) {
            Vec3 dir = target.subtract(currentPos).normalize();
            double moveSpeed = Math.min(FLY_SPEED, dist);
            player.moveTo(
                    currentPos.x + dir.x * moveSpeed,
                    currentPos.y + dir.y * moveSpeed,
                    currentPos.z + dir.z * moveSpeed
            );
            yVelocity = 0;
            bot.lookAt(target.x, target.y, target.z);
            return;
        }

        Vec3 direction = target.subtract(currentPos).normalize();

        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, direction)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }

        if (lastPos != null && currentPos.distanceTo(lastPos) < 0.01) {
            ticksStuck++;
            if (ticksStuck > 20) {
                player.moveTo(
                        currentPos.x + direction.x * 2.0,
                        currentPos.y + 1.0,
                        currentPos.z + direction.z * 2.0
                );
                yVelocity = 0;
                ticksStuck = 0;
            }
        } else {
            ticksStuck = 0;
        }
        lastPos = currentPos;

        double speed = SPRINT_SPEED;
        player.move(MoverType.SELF, new Vec3(direction.x * speed, yVelocity, direction.z * speed));
        bot.lookAt(target.x, target.y, target.z);
    }

    private void enterPhase(Phase newPhase) {
        this.phase = newPhase;
        progress.setPhase(newPhase.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case SEARCHING -> "Searching for " + targetBlock;
            case EQUIPPING -> "Equipping tool";
            case PATHING -> "Moving to " + (targetPos != null ? targetPos.toShortString() : "target");
            case MINING -> "Mining at " + (targetPos != null ? targetPos.toShortString() : "target");
            case COLLECTING -> "Collecting drops";
            case COOLDOWN -> "Cooldown";
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
