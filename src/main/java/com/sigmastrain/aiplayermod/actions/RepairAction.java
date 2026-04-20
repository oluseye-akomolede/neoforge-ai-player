package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.item.ItemStack;

/**
 * Repair an item to full durability. Costs XP proportional to damage.
 * Bot channels energy to restore the item — no anvil or materials needed.
 */
public class RepairAction implements BotAction {
    private final int slot;
    private String result = null;

    public RepairAction(int slot) {
        this.slot = slot;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Inventory inv = player.getInventory();

        ItemStack item = inv.getItem(slot);
        if (item.isEmpty()) {
            result = "FAILED: No item in slot " + slot;
            return true;
        }
        if (!item.isDamageableItem()) {
            result = "FAILED: Item is not repairable (not damageable)";
            return true;
        }
        if (item.getDamageValue() == 0) {
            result = "Item is already at full durability";
            return true;
        }

        // Cost: 1 level per 25% durability restored
        int maxDmg = item.getMaxDamage();
        int currentDmg = item.getDamageValue();
        float fraction = (float) currentDmg / maxDmg;
        int cost = Math.max(1, (int) (fraction * 4));

        if (player.experienceLevel < cost && !player.getAbilities().instabuild) {
            result = "FAILED: Need " + cost + " XP levels to repair but only have " + player.experienceLevel;
            return true;
        }

        if (!player.getAbilities().instabuild) {
            player.giveExperienceLevels(-cost);
        }

        item.setDamageValue(0);
        result = "Repaired " + item.getHoverName().getString() + " to full durability (cost " + cost + " levels)";
        return true;
    }

    @Override
    public String getResult() { return result; }

    @Override
    public String describe() {
        return String.format("Repair(slot=%d)", slot);
    }
}
