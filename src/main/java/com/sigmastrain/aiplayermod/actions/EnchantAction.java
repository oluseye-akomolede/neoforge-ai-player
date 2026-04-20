package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.inventory.ContainerLevelAccess;
import net.minecraft.world.inventory.EnchantmentMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

/**
 * Enchanting table interaction: enchant an item using XP and lapis lazuli.
 * Takes an inventory slot for the item, a slot for lapis, and which
 * enchantment option to pick (0=top/cheapest, 1=middle, 2=bottom/best).
 */
public class EnchantAction implements BotAction {
    private final int itemSlot;
    private final int lapisSlot;
    private final int option; // 0, 1, or 2
    private String result = null;

    public EnchantAction(int itemSlot, int lapisSlot, int option) {
        this.itemSlot = itemSlot;
        this.lapisSlot = lapisSlot;
        this.option = Math.max(0, Math.min(2, option));
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Inventory inv = player.getInventory();

        ItemStack item = inv.getItem(itemSlot);
        ItemStack lapis = inv.getItem(lapisSlot);

        if (item.isEmpty()) { result = "FAILED: No item in slot " + itemSlot; return true; }
        if (lapis.isEmpty() || lapis.getItem() != Items.LAPIS_LAZULI) {
            result = "FAILED: No lapis lazuli in slot " + lapisSlot;
            return true;
        }

        BlockPos tablePos = findNearbyBlock(player, "enchanting_table", 6);
        if (tablePos == null) { result = "FAILED: No enchanting table within 6 blocks"; return true; }

        ContainerLevelAccess access = ContainerLevelAccess.create(player.level(), tablePos);

        EnchantmentMenu menu = new EnchantmentMenu(
                player.containerMenu.containerId + 1, inv, access);

        menu.getSlot(0).set(item.copy());
        menu.getSlot(1).set(lapis.copy());

        menu.slotsChanged(menu.getSlot(0).container);

        if (menu.costs[option] <= 0) {
            result = "FAILED: Enchantment option " + option + " not available (item may not be enchantable)";
            menu.removed(player);
            return true;
        }
        if (player.experienceLevel < menu.costs[option] && !player.getAbilities().instabuild) {
            result = "FAILED: Need " + menu.costs[option] + " XP levels but only have " + player.experienceLevel + ". Use meditate to earn more XP first.";
            menu.removed(player);
            return true;
        }
        if (lapis.getCount() < option + 1) {
            result = "FAILED: Need " + (option + 1) + " lapis but only have " + lapis.getCount();
            menu.removed(player);
            return true;
        }

        if (menu.clickMenuButton(player, option)) {
            ItemStack enchanted = menu.getSlot(0).getItem();
            int lapisUsed = option + 1;

            inv.setItem(itemSlot, enchanted.copy());
            inv.getItem(lapisSlot).shrink(lapisUsed);
            result = "Enchanted successfully (cost " + menu.costs[option] + " levels)";
        } else {
            result = "FAILED: Enchantment application failed";
        }

        menu.removed(player);
        return true;
    }

    @Override
    public String getResult() { return result; }

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
        return String.format("Enchant(item=%d, lapis=%d, option=%d)", itemSlot, lapisSlot, option);
    }
}
