package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.entity.BrewingStandBlockEntity;

/**
 * Brewing stand interaction: place bottles and ingredient, wait for brewing.
 * Takes inventory slots for ingredient and up to 3 bottles, plus optional fuel.
 * Finds a nearby brewing stand and loads it up.
 */
public class BrewAction implements BotAction {
    private final int ingredientSlot;
    private final int[] bottleSlots;
    private final int fuelSlot;
    private boolean loaded = false;
    private BlockPos brewingPos;
    private int waitTicks = 0;
    private static final int MAX_WAIT = 500; // 25 seconds (brewing takes 20s)

    public BrewAction(int ingredientSlot, int[] bottleSlots, int fuelSlot) {
        this.ingredientSlot = ingredientSlot;
        this.bottleSlots = bottleSlots;
        this.fuelSlot = fuelSlot;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (!loaded) {
            return loadBrewingStand(player);
        }

        // Wait for brewing to complete
        waitTicks++;
        if (waitTicks > MAX_WAIT) {
            collectResults(player);
            return true;
        }

        // Check if brewing is done (ingredient consumed = brewing finished)
        if (player.level().getBlockEntity(brewingPos) instanceof BrewingStandBlockEntity stand) {
            if (stand.getItem(3).isEmpty() && waitTicks > 20) {
                collectResults(player);
                return true;
            }
        }

        return false; // Keep waiting
    }

    private boolean loadBrewingStand(ServerPlayer player) {
        Inventory inv = player.getInventory();

        brewingPos = findNearbyBlock(player, "brewing_stand", 6);
        if (brewingPos == null) return true; // No brewing stand found

        if (!(player.level().getBlockEntity(brewingPos) instanceof BrewingStandBlockEntity stand)) {
            return true;
        }

        // Place fuel if provided
        if (fuelSlot >= 0) {
            ItemStack fuel = inv.getItem(fuelSlot);
            if (!fuel.isEmpty() && fuel.getItem() == Items.BLAZE_POWDER) {
                stand.setItem(4, fuel.split(1));
            }
        }

        // Place bottles (slots 0-2)
        for (int i = 0; i < bottleSlots.length && i < 3; i++) {
            if (bottleSlots[i] >= 0) {
                ItemStack bottle = inv.getItem(bottleSlots[i]);
                if (!bottle.isEmpty()) {
                    stand.setItem(i, bottle.split(1));
                }
            }
        }

        // Place ingredient (slot 3)
        if (ingredientSlot >= 0) {
            ItemStack ingredient = inv.getItem(ingredientSlot);
            if (!ingredient.isEmpty()) {
                stand.setItem(3, ingredient.split(1));
            }
        }

        stand.setChanged();
        loaded = true;
        return false; // Continue ticking
    }

    private void collectResults(ServerPlayer player) {
        if (!(player.level().getBlockEntity(brewingPos) instanceof BrewingStandBlockEntity stand)) {
            return;
        }

        Inventory inv = player.getInventory();
        // Collect brewed potions from slots 0-2
        for (int i = 0; i < 3; i++) {
            ItemStack result = stand.getItem(i);
            if (!result.isEmpty()) {
                inv.add(result.copy());
                stand.setItem(i, ItemStack.EMPTY);
            }
        }
        stand.setChanged();
    }

    private BlockPos findNearbyBlock(ServerPlayer player, String blockName, int radius) {
        BlockPos center = player.blockPosition();
        for (int dx = -radius; dx <= radius; dx++) {
            for (int dy = -radius; dy <= radius; dy++) {
                for (int dz = -radius; dz <= radius; dz++) {
                    BlockPos pos = center.offset(dx, dy, dz);
                    String id = BuiltInRegistries.BLOCK.getKey(
                            player.level().getBlockState(pos).getBlock()
                    ).getPath();
                    if (id.contains(blockName)) return pos;
                }
            }
        }
        return null;
    }

    @Override
    public String describe() {
        return String.format("Brew(ingredient=%d, bottles=%d)", ingredientSlot, bottleSlots.length);
    }
}
