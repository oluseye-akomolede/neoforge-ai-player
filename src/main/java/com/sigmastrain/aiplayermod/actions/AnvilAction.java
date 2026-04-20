package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AnvilMenu;
import net.minecraft.world.inventory.ContainerLevelAccess;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.MenuProvider;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

/**
 * Anvil interaction: combine items, apply enchanted books, or rename items.
 * Modes:
 *   - combine: put inputSlot + materialSlot items into anvil, take result
 *   - rename: put inputSlot item into anvil, rename to newName, take result
 */
public class AnvilAction implements BotAction {
    private final int inputSlot;
    private final int materialSlot;
    private final String newName;

    public AnvilAction(int inputSlot, int materialSlot, String newName) {
        this.inputSlot = inputSlot;
        this.materialSlot = materialSlot;
        this.newName = newName;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Inventory inv = player.getInventory();

        ItemStack inputItem = inv.getItem(inputSlot).copy();
        if (inputItem.isEmpty()) return true;

        ItemStack materialItem = materialSlot >= 0 ? inv.getItem(materialSlot).copy() : ItemStack.EMPTY;

        // Find nearby anvil or create virtual access
        BlockPos anvilPos = findNearbyBlock(player, "anvil", 6);

        ContainerLevelAccess access = anvilPos != null
                ? ContainerLevelAccess.create(player.level(), anvilPos)
                : ContainerLevelAccess.NULL;

        AnvilMenu anvil = new AnvilMenu(player.containerMenu.containerId + 1, inv, access);

        // Place items
        anvil.getSlot(0).set(inputItem);
        if (!materialItem.isEmpty()) {
            anvil.getSlot(1).set(materialItem);
        }

        // Rename if requested
        if (newName != null && !newName.isEmpty()) {
            anvil.setItemName(newName);
        }

        // Trigger result calculation
        anvil.createResult();

        ItemStack result = anvil.getSlot(2).getItem();
        if (result.isEmpty()) return true;

        int cost = anvil.getCost();
        if (player.experienceLevel < cost && !player.getAbilities().instabuild) {
            return true;
        }

        // Consume inputs from real inventory
        inv.getItem(inputSlot).shrink(inputItem.getCount());
        if (materialSlot >= 0 && !materialItem.isEmpty()) {
            inv.getItem(materialSlot).shrink(materialItem.getCount());
        }

        // Deduct XP
        if (!player.getAbilities().instabuild) {
            player.giveExperienceLevels(-cost);
        }

        // Give result
        inv.add(result.copy());

        return true;
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
        if (newName != null && !newName.isEmpty()) {
            return String.format("Anvil(rename slot %d to '%s')", inputSlot, newName);
        }
        return String.format("Anvil(combine slots %d + %d)", inputSlot, materialSlot);
    }
}
