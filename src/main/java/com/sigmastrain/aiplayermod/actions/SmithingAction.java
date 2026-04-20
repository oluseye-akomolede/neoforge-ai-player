package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.inventory.ContainerLevelAccess;
import net.minecraft.world.inventory.SmithingMenu;
import net.minecraft.world.item.ItemStack;

/**
 * Smithing table interaction: netherite upgrades, armor trims, etc.
 * Takes three inventory slots: template, base item, addition material.
 */
public class SmithingAction implements BotAction {
    private final int templateSlot;
    private final int baseSlot;
    private final int additionSlot;

    public SmithingAction(int templateSlot, int baseSlot, int additionSlot) {
        this.templateSlot = templateSlot;
        this.baseSlot = baseSlot;
        this.additionSlot = additionSlot;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Inventory inv = player.getInventory();

        ItemStack template = inv.getItem(templateSlot).copy();
        ItemStack base = inv.getItem(baseSlot).copy();
        ItemStack addition = inv.getItem(additionSlot).copy();

        if (base.isEmpty()) return true;

        BlockPos tablePos = findNearbyBlock(player, "smithing_table", 6);
        ContainerLevelAccess access = tablePos != null
                ? ContainerLevelAccess.create(player.level(), tablePos)
                : ContainerLevelAccess.NULL;

        SmithingMenu menu = new SmithingMenu(player.containerMenu.containerId + 1, inv, access);

        // Place items in smithing slots
        menu.getSlot(0).set(template.copy());
        menu.getSlot(1).set(base.copy());
        menu.getSlot(2).set(addition.copy());

        // Trigger result calculation
        menu.createResult();

        ItemStack result = menu.getSlot(3).getItem();
        if (result.isEmpty()) return true;

        // Consume inputs from real inventory
        inv.getItem(templateSlot).shrink(1);
        inv.getItem(baseSlot).shrink(1);
        inv.getItem(additionSlot).shrink(1);

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
        return String.format("Smithing(template=%d, base=%d, addition=%d)", templateSlot, baseSlot, additionSlot);
    }
}
