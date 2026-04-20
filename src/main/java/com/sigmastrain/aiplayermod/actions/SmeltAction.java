package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.entity.AbstractFurnaceBlockEntity;

/**
 * Smelt items in a nearby furnace/blast furnace/smoker.
 * Loads input + fuel, waits for completion, collects results.
 */
public class SmeltAction implements BotAction {
    private final int inputSlot;
    private final int fuelSlot;
    private final int count;
    private boolean loaded = false;
    private BlockPos furnacePos;
    private int waitTicks = 0;
    private int itemsToSmelt;
    private String result = null;
    private static final int MAX_WAIT = 600; // 30 seconds max

    public SmeltAction(int inputSlot, int fuelSlot, int count) {
        this.inputSlot = inputSlot;
        this.fuelSlot = fuelSlot;
        this.count = Math.max(1, Math.min(64, count));
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (!loaded) {
            return loadFurnace(player);
        }

        waitTicks++;
        if (waitTicks > MAX_WAIT) {
            collectResults(player);
            return true;
        }

        // Check if smelting is done (input slot empty in furnace)
        if (player.level().getBlockEntity(furnacePos) instanceof AbstractFurnaceBlockEntity furnace) {
            if (furnace.getItem(0).isEmpty() && waitTicks > 40) {
                collectResults(player);
                return true;
            }
        }

        return false;
    }

    private boolean loadFurnace(ServerPlayer player) {
        Inventory inv = player.getInventory();

        // Find any type of furnace nearby
        furnacePos = findNearbyFurnace(player, 6);
        if (furnacePos == null) {
            result = "FAILED: No furnace, blast furnace, or smoker within 6 blocks";
            return true;
        }

        if (!(player.level().getBlockEntity(furnacePos) instanceof AbstractFurnaceBlockEntity furnace)) {
            result = "FAILED: Block entity is not a furnace";
            return true;
        }

        ItemStack input = inv.getItem(inputSlot);
        if (input.isEmpty()) {
            result = "FAILED: No item in input slot " + inputSlot;
            return true;
        }

        ItemStack fuel = inv.getItem(fuelSlot);
        if (fuel.isEmpty()) {
            result = "FAILED: No fuel in slot " + fuelSlot;
            return true;
        }

        // Load input
        itemsToSmelt = Math.min(count, input.getCount());
        ItemStack inputToLoad = input.split(itemsToSmelt);
        furnace.setItem(0, inputToLoad);

        // Load fuel (enough for the job — 1 coal smelts 8)
        int fuelNeeded = Math.max(1, (itemsToSmelt + 7) / 8);
        int fuelToLoad = Math.min(fuelNeeded, fuel.getCount());
        ItemStack fuelStack = fuel.split(fuelToLoad);
        furnace.setItem(1, fuelStack);

        furnace.setChanged();
        loaded = true;
        return false;
    }

    private void collectResults(ServerPlayer player) {
        if (!(player.level().getBlockEntity(furnacePos) instanceof AbstractFurnaceBlockEntity furnace)) {
            result = "FAILED: Furnace disappeared";
            return;
        }

        Inventory inv = player.getInventory();

        // Collect output (slot 2)
        ItemStack output = furnace.getItem(2);
        int collected = 0;
        if (!output.isEmpty()) {
            collected = output.getCount();
            inv.add(output.copy());
            furnace.setItem(2, ItemStack.EMPTY);
        }

        // Return any unprocessed input
        ItemStack remaining = furnace.getItem(0);
        if (!remaining.isEmpty()) {
            inv.add(remaining.copy());
            furnace.setItem(0, ItemStack.EMPTY);
        }

        // Return leftover fuel
        ItemStack leftFuel = furnace.getItem(1);
        if (!leftFuel.isEmpty()) {
            inv.add(leftFuel.copy());
            furnace.setItem(1, ItemStack.EMPTY);
        }

        furnace.setChanged();
        result = "Smelted " + collected + " item(s) from " + itemsToSmelt + " input";
    }

    private BlockPos findNearbyFurnace(ServerPlayer player, int radius) {
        BlockPos center = player.blockPosition();
        for (int dx = -radius; dx <= radius; dx++) {
            for (int dy = -radius; dy <= radius; dy++) {
                for (int dz = -radius; dz <= radius; dz++) {
                    BlockPos pos = center.offset(dx, dy, dz);
                    if (player.level().getBlockEntity(pos) instanceof AbstractFurnaceBlockEntity) {
                        return pos;
                    }
                }
            }
        }
        return null;
    }

    @Override
    public String getResult() { return result; }

    @Override
    public String describe() {
        return String.format("Smelt(input=%d, fuel=%d, count=%d)", inputSlot, fuelSlot, count);
    }
}
