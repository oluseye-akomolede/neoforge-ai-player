package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.ModMenuTypes;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.world.Container;
import net.minecraft.world.SimpleContainer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;

public class BotEquipmentMenu extends AbstractContainerMenu {

    private static final int BOT_SLOT_COUNT = 41;

    private final Container botContainer;
    private final int botEntityId;

    public BotEquipmentMenu(int containerId, Inventory playerInventory, Container botContainer) {
        this(containerId, playerInventory, botContainer, -1);
    }

    public BotEquipmentMenu(int containerId, Inventory playerInventory, Container botContainer, int botEntityId) {
        super(ModMenuTypes.BOT_EQUIPMENT.get(), containerId);
        this.botContainer = botContainer;
        this.botEntityId = botEntityId;

        // Armor slots — left column, matching vanilla inventory.png positions
        addSlot(new Slot(botContainer, 39, 8, 8));    // HEAD
        addSlot(new Slot(botContainer, 38, 8, 26));   // CHEST
        addSlot(new Slot(botContainer, 37, 8, 44));   // LEGS
        addSlot(new Slot(botContainer, 36, 8, 62));   // FEET

        // Offhand — below player model area
        addSlot(new Slot(botContainer, 40, 77, 62));

        // Main inventory (bot slots 9-35) — 3 rows matching vanilla positions
        for (int row = 0; row < 3; row++) {
            for (int col = 0; col < 9; col++) {
                addSlot(new Slot(botContainer, 9 + row * 9 + col, 8 + col * 18, 84 + row * 18));
            }
        }

        // Hotbar (bot slots 0-8) — bottom row
        for (int col = 0; col < 9; col++) {
            addSlot(new Slot(botContainer, col, 8 + col * 18, 142));
        }

        // Player inventory — below the bot section
        for (int row = 0; row < 3; row++) {
            for (int col = 0; col < 9; col++) {
                addSlot(new Slot(playerInventory, 9 + row * 9 + col, 8 + col * 18, 180 + row * 18));
            }
        }

        // Player hotbar
        for (int col = 0; col < 9; col++) {
            addSlot(new Slot(playerInventory, col, 8 + col * 18, 238));
        }
    }

    public int getBotEntityId() {
        return botEntityId;
    }

    public static BotEquipmentMenu fromNetwork(int containerId, Inventory playerInventory, RegistryFriendlyByteBuf buf) {
        int entityId = buf.readInt();
        return new BotEquipmentMenu(containerId, playerInventory, new SimpleContainer(BOT_SLOT_COUNT), entityId);
    }

    @Override
    public ItemStack quickMoveStack(Player player, int index) {
        Slot slot = this.slots.get(index);
        if (!slot.hasItem()) return ItemStack.EMPTY;

        ItemStack stack = slot.getItem();
        ItemStack result = stack.copy();
        int botSlots = BOT_SLOT_COUNT - 5; // 36 non-equipment bot slots (indices 5-40 in menu)

        if (index < 5 + 27 + 9) {
            // From bot → player inventory
            if (!this.moveItemStackTo(stack, 5 + 27 + 9, 5 + 27 + 9 + 36, true)) {
                return ItemStack.EMPTY;
            }
        } else {
            // From player → bot main inventory (skip armor/offhand)
            if (!this.moveItemStackTo(stack, 5, 5 + 27, false)) {
                if (!this.moveItemStackTo(stack, 5 + 27, 5 + 27 + 9, false)) {
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
}
