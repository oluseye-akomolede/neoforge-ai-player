package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ArmorItem;
import net.minecraft.world.item.Equipable;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.ShieldItem;

/**
 * Equip whatever is at the source `slot` into the most appropriate equipment
 * slot on the bot. Resolution order:
 *   1. ItemStack's Equippable data component (1.21 vanilla way)
 *   2. ItemStack.getEquipmentSlot() legacy hint
 *   3. Item registry path heuristics (helmet/chestplate/leggings/boots etc.)
 *   4. Shield → offhand
 *   5. Fallback → first empty hotbar slot, then mainhand select
 *
 * The "into bot's available slots" rule:
 *   - Armor: prefer EMPTY armor slot of the right type; never overwrite an
 *     already-equipped item with the same type unless the new one is upgraded.
 *   - Hotbar fallback: find empty hotbar slot. If none, find empty main-inv
 *     slot and swap. NEVER displace a non-empty hotbar slot 0 silently.
 */
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

        // 1) Detect the target slot via the proper data component first.
        EquipmentSlot targetSlot = detectArmorSlot(stack);

        if (targetSlot != null && targetSlot.getType() == EquipmentSlot.Type.HUMANOID_ARMOR) {
            int armorInvSlot = armorSlotToInventorySlot(targetSlot);
            ItemStack existing = player.getInventory().getItem(armorInvSlot);

            // If the slot already has the SAME item type, no-op (avoid redundant swaps).
            if (!existing.isEmpty() && ItemStack.isSameItem(existing, stack)) {
                return true;
            }
            // Swap: new piece goes to armor slot, displaced piece (if any) returns to source.
            player.getInventory().setItem(armorInvSlot, stack.copy());
            player.getInventory().setItem(slot, existing);
            bot.broadcastEquipmentChange(targetSlot, stack);
            return true;
        }

        if (stack.getItem() instanceof ShieldItem) {
            ItemStack existing = player.getInventory().getItem(40);
            if (!existing.isEmpty() && ItemStack.isSameItem(existing, stack)) return true;
            player.getInventory().setItem(40, stack.copy());
            player.getInventory().setItem(slot, existing);
            bot.broadcastEquipmentChange(EquipmentSlot.OFFHAND, stack);
            return true;
        }

        // Mainhand path: source slot already in hotbar → just select it.
        if (slot >= 0 && slot < 9) {
            player.getInventory().selected = slot;
            bot.broadcastEquipmentChange(EquipmentSlot.MAINHAND, stack);
            return true;
        }

        // Item is in main inventory (>=9). Move to an empty hotbar slot if possible.
        int targetHotbar = findEmptyHotbarSlot(player);
        if (targetHotbar != -1) {
            // Clean move into empty hotbar slot
            player.getInventory().setItem(targetHotbar, stack.copy());
            player.getInventory().setItem(slot, ItemStack.EMPTY);
            player.getInventory().selected = targetHotbar;
            bot.broadcastEquipmentChange(EquipmentSlot.MAINHAND, stack);
            return true;
        }

        // Hotbar full — swap with currently-selected hotbar slot.
        int swap = player.getInventory().selected;
        ItemStack existing = player.getInventory().getItem(swap);
        player.getInventory().setItem(swap, stack.copy());
        player.getInventory().setItem(slot, existing);
        bot.broadcastEquipmentChange(EquipmentSlot.MAINHAND, stack);
        return true;
    }

    /** Robust armor-slot detection.
     *  Tries ArmorItem.getEquipmentSlot() → Equipable interface → path heuristic. */
    private EquipmentSlot detectArmorSlot(ItemStack stack) {
        // 1) Vanilla ArmorItem — most reliable indicator
        if (stack.getItem() instanceof ArmorItem armor) {
            return armor.getEquipmentSlot();
        }
        // 2) Mods that implement Equipable (NeoForge's wearable hook)
        if (stack.getItem() instanceof Equipable eq) {
            EquipmentSlot s = eq.getEquipmentSlot();
            if (s != null && s.getType() == EquipmentSlot.Type.HUMANOID_ARMOR) return s;
        }
        // 3) Path-based guess for older / non-conforming mods
        return guessArmorSlotFromId(stack);
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
        String id = net.minecraft.core.registries.BuiltInRegistries.ITEM.getKey(stack.getItem()).getPath().toLowerCase();
        if (id.contains("helmet") || id.endsWith("_hat") || id.endsWith("_cap")
                || id.endsWith("_crown") || id.endsWith("_hood") || id.endsWith("_mask")) return EquipmentSlot.HEAD;
        if (id.contains("chestplate") || id.endsWith("_tunic") || id.endsWith("_jacket")
                || id.endsWith("_robe") || id.endsWith("_vest") || id.endsWith("_breastplate")
                || id.endsWith("_chest") || id.endsWith("_cuirass") || id.endsWith("_armor")) return EquipmentSlot.CHEST;
        if (id.contains("leggings") || id.endsWith("_pants") || id.endsWith("_trousers")
                || id.endsWith("_chausses") || id.endsWith("_skirt")) return EquipmentSlot.LEGS;
        if (id.contains("boots") || id.endsWith("_shoes") || id.endsWith("_greaves")
                || id.endsWith("_sandals") || id.endsWith("_sabatons")) return EquipmentSlot.FEET;
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
