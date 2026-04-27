package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.*;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.util.*;

/**
 * Withdraws items from containers into bot inventory.
 * Composite behavior: searches registry containers for the target item,
 * paths to each, and extracts until the requested count is met.
 *
 * Directive target = item ID to withdraw (e.g. "minecraft:iron_ingot").
 * Directive count  = how many to withdraw (default: 64).
 */
public class ContainerWithdrawBehavior implements Behavior {
    private enum Phase { VALIDATE, SEARCH, PATHING, EXTRACTING, DONE }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String itemId;
    private Item item;
    private int requested;
    private int collected;

    private List<ContainerRegistry.ContainerEntry> candidates;
    private int candidateIdx;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        collected = 0;
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

        requested = directive.getCount() > 0 ? directive.getCount() : 64;

        ServerPlayer player = bot.getPlayer();
        String dimension = player.serverLevel().dimension().location().toString();

        bot.systemChat("Withdrawing " + requested + "x " + itemId, "aqua");

        if (directive.hasLocation()) {
            BlockPos targetPos = new BlockPos((int) directive.getX(), (int) directive.getY(), (int) directive.getZ());
            var be = player.serverLevel().getBlockEntity(targetPos);
            if (be instanceof net.minecraft.world.Container) {
                var entry = ContainerRegistry.get().getByPos(targetPos);
                if (entry == null) {
                    int id = ContainerRegistry.get().register(targetPos, dimension, player.getName().getString());
                    entry = ContainerRegistry.get().get(id);
                }
                candidates = new ArrayList<>(List.of(entry));
                progress.logEvent("Withdrawing " + requested + "x " + itemId + " from container at " + targetPos.toShortString());
                phase = Phase.SEARCH;
                return;
            }
            progress.logEvent("No container at specified coords, searching registry");
        }

        candidates = ContainerRegistry.get().getByDimension(dimension);

        if (candidates.isEmpty()) {
            progress.setFailureReason("No containers registered in " + dimension);
            return;
        }

        progress.logEvent("Withdrawing " + requested + "x " + itemId + " from " + candidates.size() + " containers");
        phase = Phase.SEARCH;
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (progress.toMap().containsKey("failure_reason")) return BehaviorResult.FAILED;

        return switch (phase) {
            case VALIDATE -> BehaviorResult.FAILED;
            case SEARCH -> tickSearch(bot);
            case PATHING -> tickPathing(bot);
            case EXTRACTING -> tickExtracting(bot);
            case DONE -> BehaviorResult.SUCCESS;
        };
    }

    private BehaviorResult tickSearch(BotPlayer bot) {
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

            if (containsItem(container)) {
                progress.setPhase("pathing to #" + entry.id());
                phase = Phase.PATHING;
                return BehaviorResult.RUNNING;
            }
            candidateIdx++;
        }

        if (collected > 0) {
            return finish(bot, "Withdrew " + collected + "/" + requested + "x " + itemId + " (no more found)");
        }
        progress.setFailureReason("No containers contain " + itemId);
        return BehaviorResult.FAILED;
    }

    private BehaviorResult tickPathing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ContainerRegistry.ContainerEntry entry = candidates.get(candidateIdx);
        player.moveTo(
                entry.pos().getX() + 0.5,
                entry.pos().getY(),
                entry.pos().getZ() + 0.5
        );
        phase = Phase.EXTRACTING;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickExtracting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ContainerRegistry.ContainerEntry entry = candidates.get(candidateIdx);
        BlockEntity be = player.serverLevel().getBlockEntity(entry.pos());

        if (!(be instanceof Container container)) {
            ContainerRegistry.get().remove(entry.id());
            candidateIdx++;
            phase = Phase.SEARCH;
            return BehaviorResult.RUNNING;
        }

        int remaining = requested - collected;
        for (int slot = 0; slot < container.getContainerSize() && remaining > 0; slot++) {
            ItemStack stack = container.getItem(slot);
            if (stack.isEmpty() || !stack.is(item)) continue;

            int toTake = Math.min(remaining, stack.getCount());
            ItemStack extracted = stack.split(toTake);
            if (!player.getInventory().add(extracted)) {
                stack.grow(extracted.getCount());
                if (collected > 0) {
                    container.setChanged();
                    return finish(bot, "Withdrew " + collected + "x " + itemId + " (inventory full)");
                }
                progress.setFailureReason("Bot inventory full");
                return BehaviorResult.FAILED;
            }
            collected += toTake;
            remaining -= toTake;
        }

        container.setChanged();

        if (collected >= requested) {
            return finish(bot, "Withdrew " + collected + "x " + itemId);
        }

        candidateIdx++;
        phase = Phase.SEARCH;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult finish(BotPlayer bot, String message) {
        phase = Phase.DONE;
        progress.increment("items_withdrawn", collected);
        progress.logEvent(message);
        bot.systemChat(message, "green");
        return BehaviorResult.SUCCESS;
    }

    private boolean containsItem(Container container) {
        for (int i = 0; i < container.getContainerSize(); i++) {
            ItemStack stack = container.getItem(i);
            if (!stack.isEmpty() && stack.is(item)) return true;
        }
        return false;
    }

    @Override
    public String describeState() {
        return "Withdrawing " + itemId + " (" + collected + "/" + requested + ")";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
