package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.mojang.datafixers.util.Pair;
import net.minecraft.network.protocol.game.ClientboundSetEquipmentPacket;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ArmorItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.ShieldItem;

import java.util.List;

public class EquipAction implements BotAction {
    private final int slot;

    public EquipAction(int slot) {
        this.slot = slot;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        if (slot < 0 || slot >= player.getInventory().getContainerSize()) {
            return true;
        }

        ItemStack stack = player.getInventory().getItem(slot);
        if (stack.isEmpty()) {
            return true;
        }

        if (stack.getItem() instanceof ArmorItem armor) {
            EquipmentSlot equipSlot = armor.getEquipmentSlot();
            int armorInvSlot = armorSlotToInventorySlot(equipSlot);
            ItemStack existing = player.getInventory().getItem(armorInvSlot);
            player.getInventory().setItem(armorInvSlot, stack.copy());
            player.getInventory().setItem(slot, existing);
            broadcastEquipment(player, equipSlot, stack);
        } else if (stack.getItem() instanceof ShieldItem) {
            ItemStack existing = player.getInventory().getItem(40);
            player.getInventory().setItem(40, stack.copy());
            player.getInventory().setItem(slot, existing);
            broadcastEquipment(player, EquipmentSlot.OFFHAND, stack);
        } else if (slot >= 0 && slot < 9) {
            player.getInventory().selected = slot;
            broadcastEquipment(player, EquipmentSlot.MAINHAND, stack);
        } else {
            int targetHotbar = findEmptyHotbarSlot(player);
            if (targetHotbar == -1) targetHotbar = 0;
            ItemStack existing = player.getInventory().getItem(targetHotbar);
            player.getInventory().setItem(targetHotbar, stack.copy());
            player.getInventory().setItem(slot, existing);
            player.getInventory().selected = targetHotbar;
            broadcastEquipment(player, EquipmentSlot.MAINHAND, stack);
        }

        return true;
    }

    private void broadcastEquipment(ServerPlayer player, EquipmentSlot equipSlot, ItemStack stack) {
        ClientboundSetEquipmentPacket packet = new ClientboundSetEquipmentPacket(
                player.getId(),
                List.of(Pair.of(equipSlot, stack.copy()))
        );
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) {
            online.connection.send(packet);
        }
    }

    private int armorSlotToInventorySlot(EquipmentSlot slot) {
        return switch (slot) {
            case FEET -> 36;
            case LEGS -> 37;
            case CHEST -> 38;
            case HEAD -> 39;
            default -> 36;
        };
    }

    private int findEmptyHotbarSlot(ServerPlayer player) {
        for (int i = 0; i < 9; i++) {
            if (player.getInventory().getItem(i).isEmpty()) return i;
        }
        return -1;
    }

    @Override
    public String describe() {
        return "Equip(slot=" + slot + ")";
    }
}
