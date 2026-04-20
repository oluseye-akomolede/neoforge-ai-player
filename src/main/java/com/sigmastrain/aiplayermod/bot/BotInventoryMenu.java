package com.sigmastrain.aiplayermod.bot;

import net.minecraft.world.SimpleContainer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.MenuType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.network.chat.Component;

public class BotInventoryMenu extends AbstractContainerMenu {

    private static final int BOT_ROWS = 6;
    private static final int BOT_SLOTS = BOT_ROWS * 9;

    private final SimpleContainer paneContainer;
    private final Inventory botInventory;

    public BotInventoryMenu(int containerId, Inventory playerInventory, Inventory botInventory) {
        super(MenuType.GENERIC_9x6, containerId);

        this.botInventory = botInventory;
        this.paneContainer = new SimpleContainer(BOT_SLOTS);
        setupPanes();

        // Row 0: Armor (HEAD/CHEST/LEGS/FEET) + pane + Offhand + panes + label
        addSlot(new BotInvSlot(botInventory, 39, 8, 18));       // HEAD
        addSlot(new BotInvSlot(botInventory, 38, 26, 18));      // CHEST
        addSlot(new BotInvSlot(botInventory, 37, 44, 18));      // LEGS
        addSlot(new BotInvSlot(botInventory, 36, 62, 18));      // FEET
        addSlot(new LockedSlot(paneContainer, 4, 80, 18));      // pane
        addSlot(new BotInvSlot(botInventory, 40, 98, 18));      // OFFHAND
        addSlot(new LockedSlot(paneContainer, 6, 116, 18));     // pane
        addSlot(new LockedSlot(paneContainer, 7, 134, 18));     // pane
        addSlot(new LockedSlot(paneContainer, 8, 152, 18));     // label

        // Row 1: Hotbar (bot slots 0-8)
        for (int i = 0; i < 9; i++) {
            addSlot(new BotInvSlot(botInventory, i, 8 + i * 18, 36));
        }

        // Row 2: Divider panes (all locked)
        for (int i = 0; i < 9; i++) {
            addSlot(new LockedSlot(paneContainer, 18 + i, 8 + i * 18, 54));
        }

        // Rows 3-5: Main inventory (bot slots 9-35)
        for (int i = 9; i < 36; i++) {
            int row = (i - 9) / 9;
            int col = (i - 9) % 9;
            addSlot(new BotInvSlot(botInventory, i, 8 + col * 18, 72 + row * 18));
        }

        // Player's inventory — 3 rows
        for (int row = 0; row < 3; row++) {
            for (int col = 0; col < 9; col++) {
                addSlot(new Slot(playerInventory, col + row * 9 + 9, 8 + col * 18, 140 + row * 18));
            }
        }

        // Player's hotbar
        for (int col = 0; col < 9; col++) {
            addSlot(new Slot(playerInventory, col, 8 + col * 18, 198));
        }
    }

    private void setupPanes() {
        paneContainer.setItem(4, makeLabel(Items.ORANGE_STAINED_GLASS_PANE, " "));
        paneContainer.setItem(6, makeLabel(Items.ORANGE_STAINED_GLASS_PANE, " "));
        paneContainer.setItem(7, makeLabel(Items.ORANGE_STAINED_GLASS_PANE, " "));
        paneContainer.setItem(8, makeLabel(Items.ORANGE_STAINED_GLASS_PANE, "\u2190 Armor / Offhand"));
        for (int i = 0; i < 8; i++) {
            paneContainer.setItem(18 + i, makeLabel(Items.LIME_STAINED_GLASS_PANE, " "));
        }
        paneContainer.setItem(26, makeLabel(Items.LIME_STAINED_GLASS_PANE, "\u2191 Hotbar / Inventory \u2193"));
    }

    private ItemStack makeLabel(net.minecraft.world.level.ItemLike item, String name) {
        ItemStack stack = new ItemStack(item);
        stack.set(net.minecraft.core.component.DataComponents.CUSTOM_NAME,
                Component.literal(name).withStyle(s -> s.withItalic(false)));
        return stack;
    }

    @Override
    public ItemStack quickMoveStack(Player player, int index) {
        Slot slot = this.slots.get(index);
        if (!slot.hasItem()) return ItemStack.EMPTY;
        if (slot instanceof LockedSlot) return ItemStack.EMPTY;

        ItemStack stack = slot.getItem();
        ItemStack result = stack.copy();

        if (index < BOT_SLOTS) {
            // Moving from bot inventory to player inventory
            if (!this.moveItemStackTo(stack, BOT_SLOTS, BOT_SLOTS + 36, true)) {
                return ItemStack.EMPTY;
            }
        } else {
            // Moving from player inventory to bot inventory (try main inv rows 3-5 first)
            if (!this.moveItemStackTo(stack, 18, BOT_SLOTS, false)) {
                // Try hotbar row
                if (!this.moveItemStackTo(stack, 9, 18, false)) {
                    return ItemStack.EMPTY;
                }
            }
        }

        if (stack.isEmpty()) {
            slot.setByPlayer(ItemStack.EMPTY);
        } else {
            slot.setChanged();
        }
        return result;
    }

    @Override
    public boolean stillValid(Player player) {
        return true;
    }

    private static class BotInvSlot extends Slot {
        public BotInvSlot(Inventory inventory, int index, int x, int y) {
            super(inventory, index, x, y);
        }
    }

    private static class LockedSlot extends Slot {
        public LockedSlot(SimpleContainer container, int index, int x, int y) {
            super(container, index, x, y);
        }

        @Override
        public boolean mayPlace(ItemStack stack) {
            return false;
        }

        @Override
        public boolean mayPickup(Player player) {
            return false;
        }
    }
}
