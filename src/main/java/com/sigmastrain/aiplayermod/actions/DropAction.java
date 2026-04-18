package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;

public class DropAction implements BotAction {
    private final int slot;
    private final int count;

    public DropAction(int slot, int count) {
        this.slot = slot;
        this.count = count;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ItemStack stack = player.getInventory().getItem(slot);
        if (!stack.isEmpty()) {
            int toDrop = Math.min(count, stack.getCount());
            ItemStack dropped = stack.split(toDrop);
            player.drop(dropped, false);
        }
        return true;
    }

    @Override
    public String describe() {
        return String.format("Drop(slot=%d, count=%d)", slot, count);
    }
}
