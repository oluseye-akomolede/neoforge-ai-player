package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ArmorItem;
import net.minecraft.world.item.Equipable;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.ShieldItem;

/**
 * Smart bulk equip: scans the bot's inventory in one tick, finds every
 * equippable item (armor + shield), and puts each into the matching slot.
 * Skips slots that already hold the same item; replaces lower-tier armor
 * with higher-tier (by max durability as a coarse proxy) when both are
 * present in inventory.
 *
 * Used by the "equip_all" session action so the LLM can say "equip yourself"
 * without having to enumerate slot numbers per piece.
 */
public class EquipAllAction implements BotAction {

    private int equipped = 0;

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        equipped = 0;

        // Pick the best candidate for each armor slot from main inventory.
        ItemStack bestHead = ItemStack.EMPTY;
        int bestHeadSlot = -1;
        ItemStack bestChest = ItemStack.EMPTY;
        int bestChestSlot = -1;
        ItemStack bestLegs = ItemStack.EMPTY;
        int bestLegsSlot = -1;
        ItemStack bestFeet = ItemStack.EMPTY;
        int bestFeetSlot = -1;
        ItemStack bestShield = ItemStack.EMPTY;
        int bestShieldSlot = -1;

        for (int i = 0; i < 36; i++) {  // 0-8 hotbar, 9-35 main inventory
            ItemStack s = player.getInventory().getItem(i);
            if (s.isEmpty()) continue;
            EquipmentSlot slot = detectArmorSlot(s);
            if (slot != null) {
                switch (slot) {
                    case HEAD -> { if (isBetter(s, bestHead)) { bestHead = s; bestHeadSlot = i; } }
                    case CHEST -> { if (isBetter(s, bestChest)) { bestChest = s; bestChestSlot = i; } }
                    case LEGS -> { if (isBetter(s, bestLegs)) { bestLegs = s; bestLegsSlot = i; } }
                    case FEET -> { if (isBetter(s, bestFeet)) { bestFeet = s; bestFeetSlot = i; } }
                    default -> { /* main/offhand body slot — skip armor path */ }
                }
            } else if (s.getItem() instanceof ShieldItem) {
                if (isBetter(s, bestShield)) { bestShield = s; bestShieldSlot = i; }
            }
        }

        // Apply each best-of-type to its target slot if the current piece is empty
        // or strictly worse.
        equipped += tryEquipArmor(player, bot, bestHead, bestHeadSlot, EquipmentSlot.HEAD, 39);
        equipped += tryEquipArmor(player, bot, bestChest, bestChestSlot, EquipmentSlot.CHEST, 38);
        equipped += tryEquipArmor(player, bot, bestLegs, bestLegsSlot, EquipmentSlot.LEGS, 37);
        equipped += tryEquipArmor(player, bot, bestFeet, bestFeetSlot, EquipmentSlot.FEET, 36);

        if (!bestShield.isEmpty()) {
            ItemStack existingOff = player.getInventory().getItem(40);
            if (existingOff.isEmpty() || !ItemStack.isSameItem(existingOff, bestShield)) {
                player.getInventory().setItem(40, bestShield.copy());
                player.getInventory().setItem(bestShieldSlot, existingOff);
                bot.broadcastEquipmentChange(EquipmentSlot.OFFHAND, bestShield);
                equipped++;
            }
        }
        return true;
    }

    /** Returns 1 if an equip happened, 0 if no-op. */
    private int tryEquipArmor(ServerPlayer player, BotPlayer bot,
                              ItemStack candidate, int srcSlot,
                              EquipmentSlot dst, int armorInvSlot) {
        if (candidate.isEmpty() || srcSlot < 0) return 0;
        ItemStack existing = player.getInventory().getItem(armorInvSlot);
        if (!existing.isEmpty() && ItemStack.isSameItem(existing, candidate)) return 0;
        if (!existing.isEmpty() && !isBetter(candidate, existing)) return 0;
        player.getInventory().setItem(armorInvSlot, candidate.copy());
        player.getInventory().setItem(srcSlot, existing);
        bot.broadcastEquipmentChange(dst, candidate);
        return 1;
    }

    /** Coarse "better" check: any item beats empty; otherwise compare max durability. */
    private boolean isBetter(ItemStack a, ItemStack b) {
        if (b.isEmpty()) return true;
        if (a.isEmpty()) return false;
        if (ItemStack.isSameItem(a, b)) return false;
        int da = a.getMaxDamage();
        int db = b.getMaxDamage();
        return da > db;
    }

    private EquipmentSlot detectArmorSlot(ItemStack stack) {
        if (stack.getItem() instanceof ArmorItem armor) {
            return armor.getEquipmentSlot();
        }
        if (stack.getItem() instanceof Equipable eq) {
            EquipmentSlot s = eq.getEquipmentSlot();
            if (s != null && s.getType() == EquipmentSlot.Type.HUMANOID_ARMOR) return s;
        }
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

    @Override
    public String describe() {
        return "EquipAll(equipped=" + equipped + ")";
    }
}
