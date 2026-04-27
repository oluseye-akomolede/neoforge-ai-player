package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.*;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.Container;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.util.*;

/**
 * Stores items from bot inventory into a container.
 * Composite behavior: searches registry for a container with space,
 * paths to it, and deposits. If no container exists, conjures one first.
 *
 * Directive target = item ID to store (e.g. "minecraft:cobblestone").
 * Directive count  = how many to store (default: all of that item).
 */
public class ContainerStoreBehavior implements Behavior {
    private enum Phase { VALIDATE, FIND_CONTAINER, PATHING, DEPOSITING, PLACING, PLACE_DEPOSIT }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String itemId;
    private Item item;
    private int requested;
    private int deposited;

    private List<ContainerRegistry.ContainerEntry> candidates;
    private int candidateIdx;
    private ContainerRegistry.ContainerEntry currentTarget;

    private BlockPos placePos;
    private int placeTicks;
    private static final int PLACE_TICKS = 40;
    private static final int PLACE_XP_COST = 3;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        deposited = 0;
        candidateIdx = 0;

        itemId = directive.getTarget();
        if (itemId == null || itemId.isEmpty()) {
            progress.setFailureReason("No item specified");
            return;
        }
        if (!itemId.contains(":")) itemId = "minecraft:" + itemId;

        item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        if (item == Items.AIR) {
            progress.setFailureReason("Unknown item: " + itemId);
            return;
        }

        int inInventory = countInInventory(bot);
        if (inInventory == 0) {
            progress.setFailureReason("No " + itemId + " in inventory");
            return;
        }

        requested = directive.getCount() > 0 ? Math.min(directive.getCount(), inInventory) : inInventory;

        ServerPlayer player = bot.getPlayer();
        String dimension = player.serverLevel().dimension().location().toString();

        bot.systemChat("Storing " + requested + "x " + itemId, "aqua");
        progress.logEvent("Storing " + requested + "x " + itemId);

        if (directive.hasLocation()) {
            BlockPos targetPos = new BlockPos((int) directive.getX(), (int) directive.getY(), (int) directive.getZ());
            var be = player.serverLevel().getBlockEntity(targetPos);
            if (be instanceof Container) {
                currentTarget = ContainerRegistry.get().getByPos(targetPos);
                if (currentTarget == null) {
                    int id = ContainerRegistry.get().register(targetPos, dimension, player.getName().getString());
                    currentTarget = ContainerRegistry.get().get(id);
                }
                phase = Phase.PATHING;
                return;
            }
            progress.logEvent("No container at specified coords, searching registry");
        }

        candidates = ContainerRegistry.get().getByDimension(dimension);
        if (candidates.isEmpty()) {
            enterPlacing(bot);
        } else {
            phase = Phase.FIND_CONTAINER;
        }
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (progress.toMap().containsKey("failure_reason")) return BehaviorResult.FAILED;

        return switch (phase) {
            case VALIDATE -> BehaviorResult.FAILED;
            case FIND_CONTAINER -> tickFindContainer(bot);
            case PATHING -> tickPathing(bot);
            case DEPOSITING -> tickDepositing(bot);
            case PLACING -> tickPlacing(bot);
            case PLACE_DEPOSIT -> tickDepositing(bot);
        };
    }

    private BehaviorResult tickFindContainer(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        while (candidateIdx < candidates.size()) {
            ContainerRegistry.ContainerEntry entry = candidates.get(candidateIdx);
            BlockEntity be = level.getBlockEntity(entry.pos());

            if (!(be instanceof Container container)) {
                ContainerRegistry.get().remove(entry.id());
                progress.logEvent("Container #" + entry.id() + " missing — removed");
                candidateIdx++;
                continue;
            }

            if (hasSpace(container)) {
                currentTarget = entry;
                phase = Phase.PATHING;
                return BehaviorResult.RUNNING;
            }
            candidateIdx++;
        }

        enterPlacing(bot);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickPathing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        player.moveTo(
                currentTarget.pos().getX() + 0.5,
                currentTarget.pos().getY(),
                currentTarget.pos().getZ() + 0.5
        );
        progress.setPhase("pathing to #" + currentTarget.id());
        phase = Phase.DEPOSITING;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickDepositing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        BlockPos pos = phase == Phase.PLACE_DEPOSIT ? placePos : currentTarget.pos();
        BlockEntity be = player.serverLevel().getBlockEntity(pos);

        if (!(be instanceof Container container)) {
            if (phase == Phase.PLACE_DEPOSIT) {
                progress.setFailureReason("Placed container disappeared");
                return BehaviorResult.FAILED;
            }
            ContainerRegistry.get().remove(currentTarget.id());
            candidateIdx++;
            phase = Phase.FIND_CONTAINER;
            return BehaviorResult.RUNNING;
        }

        int remaining = requested - deposited;
        for (int invSlot = 0; invSlot < player.getInventory().getContainerSize() && remaining > 0; invSlot++) {
            ItemStack stack = player.getInventory().getItem(invSlot);
            if (stack.isEmpty() || !stack.is(item)) continue;

            int toMove = Math.min(remaining, stack.getCount());
            ItemStack toPlace = stack.copy();
            toPlace.setCount(toMove);

            boolean placed = false;
            for (int cs = 0; cs < container.getContainerSize(); cs++) {
                ItemStack existing = container.getItem(cs);
                if (existing.isEmpty()) {
                    container.setItem(cs, toPlace);
                    stack.shrink(toMove);
                    placed = true;
                    break;
                } else if (ItemStack.isSameItemSameComponents(existing, toPlace)
                        && existing.getCount() + toMove <= existing.getMaxStackSize()) {
                    existing.grow(toMove);
                    stack.shrink(toMove);
                    placed = true;
                    break;
                }
            }

            if (placed) {
                deposited += toMove;
                remaining -= toMove;
            } else {
                break;
            }
        }

        container.setChanged();

        if (deposited >= requested) {
            progress.increment("items_stored", deposited);
            progress.logEvent("Stored " + deposited + "x " + itemId);
            bot.systemChat("Stored " + deposited + "x " + itemId, "green");
            return BehaviorResult.SUCCESS;
        }

        if (phase == Phase.PLACE_DEPOSIT || candidateIdx >= candidates.size() - 1) {
            if (deposited > 0) {
                progress.increment("items_stored", deposited);
                progress.logEvent("Stored " + deposited + "/" + requested + "x " + itemId + " (containers full)");
                bot.systemChat("Stored " + deposited + "/" + requested + "x " + itemId, "yellow");
                return BehaviorResult.SUCCESS;
            }
            enterPlacing(bot);
            return BehaviorResult.RUNNING;
        }

        candidateIdx++;
        phase = Phase.FIND_CONTAINER;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickPlacing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        placeTicks++;

        if (placeTicks % 4 == 0) {
            var pos = net.minecraft.world.phys.Vec3.atCenterOf(placePos);
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 0.5, pos.z, 3, 0.3, 0.3, 0.3, 0.1);
        }

        if (placeTicks < PLACE_TICKS) return BehaviorResult.RUNNING;

        player.giveExperienceLevels(-PLACE_XP_COST);
        level.setBlock(placePos, Blocks.CHEST.defaultBlockState(), 3);
        level.playSound(null, placePos, SoundEvents.WOOD_PLACE, SoundSource.BLOCKS, 1.0f, 1.0f);

        String dimension = level.dimension().location().toString();
        int id = ContainerRegistry.get().register(placePos, dimension, player.getName().getString());

        progress.logEvent("Conjured container #" + id + " at " + placePos.toShortString());
        bot.systemChat("Conjured container #" + id, "light_purple");

        player.moveTo(placePos.getX() + 0.5, placePos.getY(), placePos.getZ() + 0.5);
        phase = Phase.PLACE_DEPOSIT;
        return BehaviorResult.RUNNING;
    }

    private void enterPlacing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        placePos = player.blockPosition().relative(Direction.fromYRot(player.getYRot()), 1);
        if (!player.level().getBlockState(placePos).isAir()) {
            placePos = player.blockPosition().above();
            if (!player.level().getBlockState(placePos).isAir()) {
                placePos = player.blockPosition();
            }
        }
        if (player.experienceLevel < PLACE_XP_COST) {
            player.giveExperienceLevels(PLACE_XP_COST - player.experienceLevel);
        }
        placeTicks = 0;
        phase = Phase.PLACING;
        progress.setPhase("conjuring container");
        bot.systemChat("No container with space — conjuring one", "light_purple");
    }

    private boolean hasSpace(Container container) {
        for (int i = 0; i < container.getContainerSize(); i++) {
            ItemStack stack = container.getItem(i);
            if (stack.isEmpty()) return true;
            if (stack.is(item) && stack.getCount() < stack.getMaxStackSize()) return true;
        }
        return false;
    }

    private int countInInventory(BotPlayer bot) {
        int count = 0;
        for (int i = 0; i < bot.getPlayer().getInventory().getContainerSize(); i++) {
            ItemStack stack = bot.getPlayer().getInventory().getItem(i);
            if (!stack.isEmpty() && stack.is(item)) count += stack.getCount();
        }
        return count;
    }

    @Override
    public String describeState() {
        return "Storing " + itemId + " (" + deposited + "/" + requested + ")";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
