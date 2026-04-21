package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.AbstractFurnaceBlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.Vec3;

/**
 * Composite smelting behavior. Handles the full chain:
 * 1. Find input items and fuel in inventory
 * 2. Find or craft+place a furnace
 * 3. Navigate to the furnace
 * 4. Load input + fuel
 * 5. Wait for smelting to complete
 * 6. Collect output
 * 7. Repeat if count > furnace capacity
 */
public class SmeltBehavior implements Behavior {
    private enum Phase {
        VALIDATE, FIND_FURNACE, CRAFT_FURNACE, PLACE_FURNACE, NAVIGATE, LOAD, WAITING, COLLECT
    }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String inputItemId;
    private int inputSlot = -1;
    private int fuelSlot = -1;
    private int totalToSmelt;
    private int totalSmelted;
    private int batchSize;
    private BlockPos furnacePos;

    private int waitTicks;

    // Navigation
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;

    // For crafting a furnace if needed
    private CraftBehavior craftFurnaceBehavior;

    private static final double REACH = 4.5;
    private static final int FURNACE_SEARCH_RADIUS = 16;
    private static final int MAX_WAIT_TICKS = 600;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.inputItemId = directive.getTarget();
        this.totalToSmelt = directive.getCount() > 0 ? directive.getCount() : 1;
        this.totalSmelted = 0;
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        this.craftFurnaceBehavior = null;
        enterPhase(Phase.VALIDATE);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case VALIDATE -> tickValidate(bot);
            case FIND_FURNACE -> tickFindFurnace(bot);
            case CRAFT_FURNACE -> tickCraftFurnace(bot);
            case PLACE_FURNACE -> tickPlaceFurnace(bot);
            case NAVIGATE -> tickNavigate(bot);
            case LOAD -> tickLoad(bot);
            case WAITING -> tickWaiting(bot);
            case COLLECT -> tickCollect(bot);
        };
    }

    private BehaviorResult tickValidate(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        // Find input items in inventory
        inputSlot = findItemSlot(player, inputItemId);
        if (inputSlot < 0) {
            progress.setFailureReason("No " + inputItemId + " in inventory");
            return BehaviorResult.FAILED;
        }

        // Find fuel in inventory (coal, charcoal, wood, etc.)
        fuelSlot = findFuelSlot(player);
        if (fuelSlot < 0) {
            progress.setFailureReason("No fuel in inventory");
            return BehaviorResult.FAILED;
        }

        int available = player.getInventory().getItem(inputSlot).getCount();
        batchSize = Math.min(totalToSmelt - totalSmelted, Math.min(available, 64));
        progress.logEvent("Will smelt " + batchSize + "x " + inputItemId);
        enterPhase(Phase.FIND_FURNACE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickFindFurnace(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        furnacePos = findNearbyFurnace(player, FURNACE_SEARCH_RADIUS);

        if (furnacePos != null) {
            progress.logEvent("Found furnace at " + furnacePos.toShortString());
            enterPhase(Phase.NAVIGATE);
            return BehaviorResult.RUNNING;
        }

        // Check inventory for a furnace
        Item furnaceItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:furnace"));
        if (countItem(player, furnaceItem) > 0) {
            enterPhase(Phase.PLACE_FURNACE);
            return BehaviorResult.RUNNING;
        }

        // Need to craft a furnace (8 cobblestone)
        Item cobble = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:cobblestone"));
        if (countItem(player, cobble) < 8) {
            progress.setFailureReason("No furnace nearby and not enough cobblestone to craft one (need 8, have " + countItem(player, cobble) + ")");
            return BehaviorResult.FAILED;
        }

        progress.logEvent("Crafting furnace from cobblestone");
        craftFurnaceBehavior = new CraftBehavior();
        Directive craftDirective = Directive.builder(com.sigmastrain.aiplayermod.brain.DirectiveType.CRAFT)
                .target("minecraft:furnace").count(1).build();
        craftFurnaceBehavior.start(bot, craftDirective);
        enterPhase(Phase.CRAFT_FURNACE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCraftFurnace(BotPlayer bot) {
        if (craftFurnaceBehavior == null) {
            enterPhase(Phase.FIND_FURNACE);
            return BehaviorResult.RUNNING;
        }
        BehaviorResult result = craftFurnaceBehavior.tick(bot);
        if (result == BehaviorResult.SUCCESS) {
            craftFurnaceBehavior = null;
            enterPhase(Phase.PLACE_FURNACE);
        } else if (result == BehaviorResult.FAILED) {
            progress.setFailureReason("Failed to craft furnace");
            return BehaviorResult.FAILED;
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickPlaceFurnace(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        BlockPos placePos = player.blockPosition().relative(player.getDirection());
        BlockState existing = player.level().getBlockState(placePos);
        if (!existing.isAir() && !existing.canBeReplaced()) {
            for (var dir : net.minecraft.core.Direction.Plane.HORIZONTAL) {
                placePos = player.blockPosition().relative(dir);
                existing = player.level().getBlockState(placePos);
                if (existing.isAir() || existing.canBeReplaced()) break;
            }
        }

        Item furnaceItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:furnace"));
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.getItem() == furnaceItem) {
                stack.shrink(1);
                break;
            }
        }

        player.level().setBlock(placePos, Blocks.FURNACE.defaultBlockState(), 3);
        furnacePos = placePos;
        progress.logEvent("Placed furnace at " + placePos.toShortString());
        enterPhase(Phase.NAVIGATE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickNavigate(BotPlayer bot) {
        if (furnacePos == null) {
            enterPhase(Phase.FIND_FURNACE);
            return BehaviorResult.RUNNING;
        }

        ServerPlayer player = bot.getPlayer();
        Vec3 target = Vec3.atCenterOf(furnacePos);
        double dist = player.position().distanceTo(target);

        if (dist <= REACH) {
            enterPhase(Phase.LOAD);
            return BehaviorResult.RUNNING;
        }

        moveToward(bot, player, target, dist);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickLoad(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (!(player.level().getBlockEntity(furnacePos) instanceof AbstractFurnaceBlockEntity furnace)) {
            progress.setFailureReason("Furnace block entity missing");
            return BehaviorResult.FAILED;
        }

        // Re-find slots in case inventory shifted
        inputSlot = findItemSlot(player, inputItemId);
        fuelSlot = findFuelSlot(player);
        if (inputSlot < 0 || fuelSlot < 0) {
            progress.setFailureReason("Lost input or fuel items");
            return BehaviorResult.FAILED;
        }

        ItemStack input = player.getInventory().getItem(inputSlot);
        ItemStack fuel = player.getInventory().getItem(fuelSlot);

        int toLoad = Math.min(batchSize, input.getCount());
        ItemStack inputToLoad = input.split(toLoad);
        furnace.setItem(0, inputToLoad);

        int fuelNeeded = Math.max(1, (toLoad + 7) / 8);
        int fuelToLoad = Math.min(fuelNeeded, fuel.getCount());
        ItemStack fuelStack = fuel.split(fuelToLoad);
        furnace.setItem(1, fuelStack);

        furnace.setChanged();
        waitTicks = 0;
        progress.logEvent("Loaded " + toLoad + " items into furnace");
        enterPhase(Phase.WAITING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickWaiting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        waitTicks++;

        if (waitTicks > MAX_WAIT_TICKS) {
            enterPhase(Phase.COLLECT);
            return BehaviorResult.RUNNING;
        }

        if (player.level().getBlockEntity(furnacePos) instanceof AbstractFurnaceBlockEntity furnace) {
            if (furnace.getItem(0).isEmpty() && waitTicks > 40) {
                enterPhase(Phase.COLLECT);
            }
        } else {
            progress.setFailureReason("Furnace disappeared while smelting");
            return BehaviorResult.FAILED;
        }

        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCollect(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (!(player.level().getBlockEntity(furnacePos) instanceof AbstractFurnaceBlockEntity furnace)) {
            progress.setFailureReason("Furnace disappeared");
            return BehaviorResult.FAILED;
        }

        // Collect output
        ItemStack output = furnace.getItem(2);
        if (!output.isEmpty()) {
            int collected = output.getCount();
            player.getInventory().add(output.copy());
            furnace.setItem(2, ItemStack.EMPTY);
            totalSmelted += collected;
            progress.increment("items_smelted", collected);
            progress.logEvent("Collected " + collected + " smelted items (" + totalSmelted + "/" + totalToSmelt + ")");
        }

        // Return unprocessed input
        ItemStack remaining = furnace.getItem(0);
        if (!remaining.isEmpty()) {
            player.getInventory().add(remaining.copy());
            furnace.setItem(0, ItemStack.EMPTY);
        }

        // Return leftover fuel
        ItemStack leftFuel = furnace.getItem(1);
        if (!leftFuel.isEmpty()) {
            player.getInventory().add(leftFuel.copy());
            furnace.setItem(1, ItemStack.EMPTY);
        }

        furnace.setChanged();

        if (totalSmelted >= totalToSmelt) {
            progress.logEvent("Smelting complete: " + totalSmelted + " items");
            return BehaviorResult.SUCCESS;
        }

        // More to smelt — loop back
        enterPhase(Phase.VALIDATE);
        return BehaviorResult.RUNNING;
    }

    private int findItemSlot(ServerPlayer player, String itemId) {
        String search = itemId.toLowerCase();
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
            if (id.contains(search)) return i;
        }
        return -1;
    }

    private int findFuelSlot(ServerPlayer player) {
        String[] fuels = {"coal", "charcoal", "lava_bucket", "blaze_rod"};
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
            for (String fuel : fuels) {
                if (id.contains(fuel)) return i;
            }
            // Any wooden item works as fuel
            if (id.contains("planks") || id.contains("log") || id.contains("wood")) return i;
        }
        return -1;
    }

    private int countItem(ServerPlayer player, Item item) {
        int count = 0;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.getItem() == item) count += stack.getCount();
        }
        return count;
    }

    private BlockPos findNearbyFurnace(ServerPlayer player, int radius) {
        BlockPos center = player.blockPosition();
        BlockPos nearest = null;
        double nearestDist = Double.MAX_VALUE;
        for (int dx = -radius; dx <= radius; dx++) {
            for (int dy = -radius; dy <= radius; dy++) {
                for (int dz = -radius; dz <= radius; dz++) {
                    BlockPos pos = center.offset(dx, dy, dz);
                    if (player.level().getBlockEntity(pos) instanceof AbstractFurnaceBlockEntity) {
                        double dist = center.distSqr(pos);
                        if (dist < nearestDist) {
                            nearestDist = dist;
                            nearest = pos;
                        }
                    }
                }
            }
        }
        return nearest;
    }

    private void moveToward(BotPlayer bot, ServerPlayer player, Vec3 target, double dist) {
        Vec3 currentPos = player.position();
        Vec3 direction = target.subtract(currentPos).normalize();

        double heightDiff = Math.abs(target.y - currentPos.y);
        if (heightDiff > 4.0) {
            double moveSpeed = Math.min(0.8, dist);
            player.moveTo(
                    currentPos.x + direction.x * moveSpeed,
                    currentPos.y + direction.y * moveSpeed,
                    currentPos.z + direction.z * moveSpeed
            );
            bot.lookAt(target.x, target.y, target.z);
            return;
        }

        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, direction)) {
                yVelocity = 0.42;
            }
        } else {
            yVelocity -= 0.08;
        }

        if (lastPos != null && currentPos.distanceTo(lastPos) < 0.01) {
            ticksStuck++;
            if (ticksStuck > 20) {
                player.moveTo(currentPos.x + direction.x * 2.0, currentPos.y + 1.0, currentPos.z + direction.z * 2.0);
                yVelocity = 0;
                ticksStuck = 0;
            }
        } else {
            ticksStuck = 0;
        }
        lastPos = currentPos;

        player.move(net.minecraft.world.entity.MoverType.SELF,
                new Vec3(direction.x * 0.4, yVelocity, direction.z * 0.4));
        bot.lookAt(target.x, target.y, target.z);
    }

    private void enterPhase(Phase newPhase) {
        this.phase = newPhase;
        progress.setPhase(newPhase.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case VALIDATE -> "Checking materials for smelting";
            case FIND_FURNACE -> "Looking for furnace";
            case CRAFT_FURNACE -> "Crafting furnace";
            case PLACE_FURNACE -> "Placing furnace";
            case NAVIGATE -> "Moving to furnace";
            case LOAD -> "Loading furnace";
            case WAITING -> "Waiting for smelting (" + waitTicks + " ticks)";
            case COLLECT -> "Collecting smelted items";
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {
        if (craftFurnaceBehavior != null) craftFurnaceBehavior.stop();
    }
}
