package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.*;
import com.sigmastrain.aiplayermod.compat.ae2.AE2Compat;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.neoforged.neoforge.items.IItemHandler;

public class MEWithdrawBehavior implements Behavior {
    private enum Phase { VALIDATE, FIND_INTERFACE, EXTRACTING, COMPLETE }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String itemId;
    private Item item;
    private int requested;
    private int extracted;
    private int searchRadius;

    private IItemHandler meHandler;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        extracted = 0;

        if (!AE2Compat.isAvailable()) {
            progress.setFailureReason("AE2 not loaded");
            phase = Phase.VALIDATE;
            return;
        }

        itemId = directive.getTarget();
        searchRadius = directive.getRadius() > 0 ? directive.getRadius() : 16;

        if (itemId == null || itemId.isEmpty()) {
            progress.setFailureReason("No item specified");
            phase = Phase.VALIDATE;
            return;
        }

        if (!itemId.contains(":")) itemId = "minecraft:" + itemId;
        item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        if (item == Items.AIR) {
            progress.setFailureReason("Unknown item: " + itemId);
            phase = Phase.VALIDATE;
            return;
        }

        requested = directive.getCount() > 0 ? directive.getCount() : 64;
        phase = Phase.FIND_INTERFACE;

        bot.systemChat("ME Withdraw: " + requested + "x " + itemId, "aqua");
        progress.logEvent("ME withdraw initiated: " + requested + "x " + itemId);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case VALIDATE -> BehaviorResult.FAILED;
            case FIND_INTERFACE -> tickFindInterface(bot);
            case EXTRACTING -> tickExtracting(bot);
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

        progress.setPhase("extracting");
        phase = Phase.EXTRACTING;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickExtracting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        int remaining = requested - extracted;

        for (int slot = 0; slot < meHandler.getSlots() && remaining > 0; slot++) {
            ItemStack inSlot = meHandler.getStackInSlot(slot);
            if (inSlot.isEmpty() || !inSlot.is(item)) continue;

            int toExtract = Math.min(remaining, inSlot.getCount());
            ItemStack extractedStack = meHandler.extractItem(slot, toExtract, false);

            if (!extractedStack.isEmpty()) {
                if (player.getInventory().add(extractedStack)) {
                    extracted += extractedStack.getCount();
                    remaining -= extractedStack.getCount();
                } else {
                    // Inventory full — put items back
                    meHandler.insertItem(slot, extractedStack, false);
                    break;
                }
            }
        }

        if (extracted > 0) {
            progress.increment("items_withdrawn", extracted);
            progress.logEvent("ME withdrew " + extracted + "x " + itemId);
            bot.systemChat("ME withdrew " + extracted + "x " + itemId, "green");
            return BehaviorResult.SUCCESS;
        }

        progress.setFailureReason("Item not found in ME network: " + itemId);
        bot.systemChat("Item not in ME network: " + itemId, "red");
        return BehaviorResult.FAILED;
    }

    @Override
    public String describeState() {
        return "ME Withdraw (" + itemId + ", " + extracted + "/" + requested + ")";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
