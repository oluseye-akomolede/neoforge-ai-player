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

/**
 * One page of a vehicle hold, opened from a bot's overlay panel. Server side
 * wraps the vehicle's live handler ({@link VehicleContainer}); client side gets
 * a placeholder of the same size — the size, page and vehicle name ride the
 * open buffer so both build an identical grid.
 */
public class BotVehicleMenu extends AbstractContainerMenu {

    private static final int COLS = 9;
    private static final int GRID_X = 8;
    private static final int GRID_Y = 18;

    private final Container hold;
    private final int slotCount;
    private final int page;
    private final int totalSlots;
    private final int botEntityId;
    private final String botName;
    private final String vehicleName;

    public int getSlotCount() { return slotCount; }
    public int getPage() { return page; }
    public int getTotalSlots() { return totalSlots; }
    public int getBotEntityId() { return botEntityId; }
    public String getBotName() { return botName; }
    public String getVehicleName() { return vehicleName; }
    public int rows() { return (slotCount + COLS - 1) / COLS; }

    /** Server constructor. */
    public BotVehicleMenu(int containerId, Inventory playerInventory, VehicleContainer hold,
                          int page, int totalSlots, int botEntityId, String botName, String vehicleName) {
        this(containerId, playerInventory, (Container) hold, page, totalSlots, botEntityId, botName, vehicleName);
    }

    private BotVehicleMenu(int containerId, Inventory playerInventory, Container hold,
                           int page, int totalSlots, int botEntityId, String botName, String vehicleName) {
        super(ModMenuTypes.BOT_VEHICLE.get(), containerId);
        this.hold = hold;
        this.slotCount = hold.getContainerSize();
        this.page = page;
        this.totalSlots = totalSlots;
        this.botEntityId = botEntityId;
        this.botName = botName;
        this.vehicleName = vehicleName;
        for (int i = 0; i < slotCount; i++) {
            addSlot(new Slot(hold, i, GRID_X + (i % COLS) * 18, GRID_Y + (i / COLS) * 18));
        }
        int top = GRID_Y + rows() * 18 + 14;
        for (int r = 0; r < 3; r++)
            for (int c = 0; c < 9; c++)
                addSlot(new Slot(playerInventory, 9 + r * 9 + c, 8 + c * 18, top + r * 18));
        for (int c = 0; c < 9; c++)
            addSlot(new Slot(playerInventory, c, 8 + c * 18, top + 3 * 18 + 4));
    }

    public static BotVehicleMenu fromNetwork(int containerId, Inventory playerInventory, RegistryFriendlyByteBuf buf) {
        int entityId = buf.readVarInt();
        String botName = buf.readUtf();
        String vehicleName = buf.readUtf();
        int total = buf.readVarInt();
        int page = buf.readVarInt();
        int count = buf.readVarInt();
        return new BotVehicleMenu(containerId, playerInventory, new SimpleContainer(count),
                page, total, entityId, botName, vehicleName);
    }

    @Override
    public ItemStack quickMoveStack(Player player, int index) {
        Slot slot = this.slots.get(index);
        if (!slot.hasItem()) return ItemStack.EMPTY;
        ItemStack stack = slot.getItem();
        ItemStack result = stack.copy();
        int playerStart = slotCount, playerEnd = slotCount + 36;
        if (index < slotCount) {
            if (!moveItemStackTo(stack, playerStart, playerEnd, true)) return ItemStack.EMPTY;
        } else {
            if (!moveItemStackTo(stack, 0, slotCount, false)) return ItemStack.EMPTY;
        }
        if (stack.isEmpty()) slot.setByPlayer(ItemStack.EMPTY); else slot.setChanged();
        return result;
    }

    @Override
    public boolean stillValid(Player player) { return true; }
}
