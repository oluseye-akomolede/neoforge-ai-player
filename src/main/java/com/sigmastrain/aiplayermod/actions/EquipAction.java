package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.mojang.datafixers.util.Pair;
import net.minecraft.network.protocol.game.ClientboundSetEquipmentPacket;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.ShieldItem;

import com.sigmastrain.aiplayermod.AIPlayerMod;
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

        String itemId = net.minecraft.core.registries.BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
        EquipmentSlot targetSlot = stack.getEquipmentSlot();
        if (targetSlot == null || targetSlot.getType() != EquipmentSlot.Type.HUMANOID_ARMOR) {
            targetSlot = guessArmorSlotFromId(stack);
        }
        if (targetSlot != null && targetSlot.getType() == EquipmentSlot.Type.HUMANOID_ARMOR) {
            int armorInvSlot = armorSlotToInventorySlot(targetSlot);
            ItemStack existing = player.getInventory().getItem(armorInvSlot);
            player.getInventory().setItem(armorInvSlot, stack.copy());
            player.getInventory().setItem(slot, existing);
            bot.broadcastEquipmentChange(targetSlot, stack);
        } else if (stack.getItem() instanceof ShieldItem) {
            ItemStack existing = player.getInventory().getItem(40);
            player.getInventory().setItem(40, stack.copy());
            player.getInventory().setItem(slot, existing);
            bot.broadcastEquipmentChange(EquipmentSlot.OFFHAND, stack);
        } else if (slot >= 0 && slot < 9) {
            player.getInventory().selected = slot;
            bot.broadcastEquipmentChange(EquipmentSlot.MAINHAND, stack);
        } else {
            int targetHotbar = findEmptyHotbarSlot(player);
            if (targetHotbar == -1) targetHotbar = 0;
            ItemStack existing = player.getInventory().getItem(targetHotbar);
            player.getInventory().setItem(targetHotbar, stack.copy());
            player.getInventory().setItem(slot, existing);
            player.getInventory().selected = targetHotbar;
            bot.broadcastEquipmentChange(EquipmentSlot.MAINHAND, stack);
        }

        return true;
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

    private EquipmentSlot guessArmorSlotFromId(ItemStack stack) {
        String id = net.minecraft.core.registries.BuiltInRegistries.ITEM.getKey(stack.getItem()).getPath();
        if (id.contains("helmet") || id.contains("_hat") || id.contains("_cap")) return EquipmentSlot.HEAD;
        if (id.contains("chestplate") || id.contains("_tunic") || id.contains("_jacket")) return EquipmentSlot.CHEST;
        if (id.contains("leggings") || id.contains("_pants") || id.contains("_trousers")) return EquipmentSlot.LEGS;
        if (id.contains("boots") || id.contains("_shoes") || id.contains("_greaves")) return EquipmentSlot.FEET;
        return null;
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
