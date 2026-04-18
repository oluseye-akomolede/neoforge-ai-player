package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ArmorItem;
import net.minecraft.world.item.ItemStack;

public class EquipAction implements BotAction {
    private final int slot;

    public EquipAction(int slot) {
        this.slot = slot;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        if (slot >= 0 && slot < 9) {
            player.getInventory().selected = slot;
        }
        return true;
    }

    @Override
    public String describe() {
        return "Equip(slot=" + slot + ")";
    }
}
