package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.*;
import com.sigmastrain.aiplayermod.compat.ae2.AE2Compat;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.neoforged.neoforge.items.IItemHandler;

public class MEStoreBehavior implements Behavior {
    private enum Phase { VALIDATE, FIND_INTERFACE, INSERTING, COMPLETE }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String targetItemId;
    private Item targetItem;
    private boolean storeAll;
    private int requested;
    private int stored;
    private int searchRadius;

    private IItemHandler meHandler;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        stored = 0;

        if (!AE2Compat.isAvailable()) {
            progress.setFailureReason("AE2 not loaded");
            phase = Phase.VALIDATE;
            return;
        }

        targetItemId = directive.getTarget();
        searchRadius = directive.getRadius() > 0 ? directive.getRadius() : 16;

        if (targetItemId == null || targetItemId.isEmpty()) {
            progress.setFailureReason("No item specified");
            phase = Phase.VALIDATE;
            return;
        }

        if ("all".equalsIgnoreCase(targetItemId)) {
            storeAll = true;
            targetItem = null;
        } else {
            storeAll = false;
            if (!targetItemId.contains(":")) targetItemId = "minecraft:" + targetItemId;
            targetItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(targetItemId));
            if (targetItem == Items.AIR) {
                progress.setFailureReason("Unknown item: " + targetItemId);
                phase = Phase.VALIDATE;
                return;
            }
        }

        requested = directive.getCount() > 0 ? directive.getCount() : Integer.MAX_VALUE;
        phase = Phase.FIND_INTERFACE;

        String desc = storeAll ? "all items" : targetItemId;
        bot.systemChat("ME Store: " + desc, "aqua");
        progress.logEvent("ME store initiated: " + desc);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case VALIDATE -> BehaviorResult.FAILED;
            case FIND_INTERFACE -> tickFindInterface(bot);
            case INSERTING -> tickInserting(bot);
            case COMPLETE -> BehaviorResult.SUCCESS;
        };
    }

    private BehaviorResult tickFindInterface(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        meHandler = AE2Compat.findNearestMEInterface(level, player.blockPosition(), searchRadius);
        if (meHandler == null) {
            progress.setFailureReason("No ME Interface found within " + searchRadius + " blocks");
            bot.systemChat("No ME Interface in range", "red");
            return BehaviorResult.FAILED;
        }

        progress.setPhase("inserting");
        phase = Phase.INSERTING;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickInserting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        int selectedSlot = player.getInventory().selected;
        int remaining = requested - stored;

        for (int i = 0; i < player.getInventory().getContainerSize() && remaining > 0; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;

            if (!storeAll) {
                if (!stack.is(targetItem)) continue;
            } else {
                if (isEssential(player, stack, i, selectedSlot)) continue;
            }

            int toInsert = Math.min(remaining, stack.getCount());
            ItemStack insertStack = stack.copy();
            insertStack.setCount(toInsert);

            ItemStack leftover = insertIntoHandler(meHandler, insertStack);
            int inserted = toInsert - leftover.getCount();

            if (inserted > 0) {
                stack.shrink(inserted);
                stored += inserted;
                remaining -= inserted;
            }

            if (!leftover.isEmpty()) break;
        }

        if (stored > 0) {
            progress.increment("items_stored", stored);
            String desc = storeAll ? "items" : targetItemId;
            progress.logEvent("ME stored " + stored + "x " + desc);
            bot.systemChat("ME stored " + stored + "x " + desc, "green");
        } else {
            String desc = storeAll ? "non-essential items" : targetItemId;
            progress.setFailureReason("No " + desc + " in inventory to store");
            return BehaviorResult.FAILED;
        }

        return BehaviorResult.SUCCESS;
    }

    private ItemStack insertIntoHandler(IItemHandler handler, ItemStack stack) {
        ItemStack remaining = stack.copy();
        for (int slot = 0; slot < handler.getSlots() && !remaining.isEmpty(); slot++) {
            remaining = handler.insertItem(slot, remaining, false);
        }
        return remaining;
    }

    private boolean isEssential(ServerPlayer player, ItemStack stack, int slot, int selectedSlot) {
        if (slot == selectedSlot) return true;
        if (slot >= 36 && slot <= 39) return true;
        if (slot == 40) return true;
        FoodProperties food = stack.getFoodProperties(player);
        return food != null;
    }

    @Override
    public String describeState() {
        String desc = storeAll ? "all" : targetItemId;
        return "ME Store (" + desc + ", " + stored + " stored)";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
