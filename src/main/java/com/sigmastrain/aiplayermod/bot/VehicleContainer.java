package com.sigmastrain.aiplayermod.bot;

import net.minecraft.world.Container;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.neoforged.neoforge.items.IItemHandler;

/**
 * A {@link Container} window over one page of a vehicle's {@link IItemHandler}
 * (Superb Warfare holds run to 102 slots — far more than a vanilla container
 * screen can show — so the menu pages 54 at a time). Write-through: every
 * read/write hits the live handler, offset by the page.
 */
public final class VehicleContainer implements Container {

    public static final int PAGE_SIZE = 54;

    private final IItemHandler handler;
    private final int offset;
    private final int size;

    public VehicleContainer(IItemHandler handler, int page) {
        this.handler = handler;
        this.offset = Math.max(0, page) * PAGE_SIZE;
        this.size = Math.max(0, Math.min(PAGE_SIZE, handler.getSlots() - offset));
    }

    public static int pages(int totalSlots) {
        return Math.max(1, (totalSlots + PAGE_SIZE - 1) / PAGE_SIZE);
    }

    @Override public int getContainerSize() { return size; }

    @Override
    public boolean isEmpty() {
        for (int i = 0; i < size; i++) if (!getItem(i).isEmpty()) return false;
        return true;
    }

    @Override
    public ItemStack getItem(int index) {
        if (index < 0 || index >= size) return ItemStack.EMPTY;
        return handler.getStackInSlot(offset + index);
    }

    @Override
    public ItemStack removeItem(int index, int count) {
        if (index < 0 || index >= size) return ItemStack.EMPTY;
        return handler.extractItem(offset + index, count, false);
    }

    @Override
    public ItemStack removeItemNoUpdate(int index) {
        if (index < 0 || index >= size) return ItemStack.EMPTY;
        ItemStack cur = handler.getStackInSlot(offset + index);
        return handler.extractItem(offset + index, cur.getCount(), false);
    }

    @Override
    public void setItem(int index, ItemStack stack) {
        if (index < 0 || index >= size) return;
        int slot = offset + index;
        // IItemHandler has no raw set; ItemStackHandler subclasses expose it.
        if (handler instanceof net.neoforged.neoforge.items.IItemHandlerModifiable m) {
            m.setStackInSlot(slot, stack);
        } else {
            ItemStack cur = handler.getStackInSlot(slot);
            if (!cur.isEmpty()) handler.extractItem(slot, cur.getCount(), false);
            if (!stack.isEmpty()) handler.insertItem(slot, stack, false);
        }
    }

    @Override public void setChanged() {}
    @Override public boolean stillValid(Player player) { return true; }

    @Override
    public boolean canPlaceItem(int index, ItemStack stack) {
        if (index < 0 || index >= size) return false;
        return handler.isItemValid(offset + index, stack);
    }

    @Override
    public void clearContent() {
        for (int i = 0; i < size; i++) setItem(i, ItemStack.EMPTY);
    }
}
