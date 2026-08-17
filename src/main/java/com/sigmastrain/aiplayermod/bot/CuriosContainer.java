package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.compat.curios.CuriosCompat;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;

import java.util.List;

/**
 * A {@link Container} adapter over a bot's Curios inventory, so vanilla slot
 * mechanics (click, drag, shift-click) work on curios slots unchanged.
 *
 * <p>Curios is not a plain container — it is a per-entity
 * {@code Map<String, ICurioStacksHandler>}. This flattens the live slot list
 * (from {@link CuriosCompat#list(ServerPlayer)}) into linear indices and
 * writes through to {@link CuriosCompat#putDirect}/{@link #getDirect} on every
 * read/write, so the screen is always looking at the real inventory.
 */
public final class CuriosContainer implements Container {

    private final ServerPlayer bot;
    private final List<CuriosCompat.WornSlot> layout;

    public CuriosContainer(ServerPlayer bot) {
        this.bot = bot;
        this.layout = CuriosCompat.list(bot);
    }

    @Override
    public int getContainerSize() {
        return layout.size();
    }

    /** The slot-type name for each linear index (for screen labels/tooltips). */
    public List<String> labels() {
        return layout.stream().map(CuriosCompat.WornSlot::slotType).toList();
    }

    @Override
    public boolean isEmpty() {
        for (int i = 0; i < layout.size(); i++) {
            if (!getItem(i).isEmpty()) return false;
        }
        return true;
    }

    @Override
    public ItemStack getItem(int index) {
        if (index < 0 || index >= layout.size()) return ItemStack.EMPTY;
        CuriosCompat.WornSlot s = layout.get(index);
        return CuriosCompat.getDirect(bot, s.slotType(), s.index());
    }

    @Override
    public ItemStack removeItem(int index, int count) {
        ItemStack cur = getItem(index);
        if (cur.isEmpty()) return ItemStack.EMPTY;
        ItemStack out = cur.split(count);
        setItem(index, cur.isEmpty() ? ItemStack.EMPTY : cur);
        return out;
    }

    @Override
    public ItemStack removeItemNoUpdate(int index) {
        ItemStack cur = getItem(index);
        if (cur.isEmpty()) return ItemStack.EMPTY;
        setItem(index, ItemStack.EMPTY);
        return cur;
    }

    @Override
    public void setItem(int index, ItemStack stack) {
        if (index < 0 || index >= layout.size()) return;
        CuriosCompat.WornSlot s = layout.get(index);
        CuriosCompat.putDirect(bot, s.slotType(), s.index(), stack);
    }

    @Override
    public void setChanged() {
        // Curios marks its own dirty state; there is no container-level flag.
    }

    @Override
    public void clearContent() {
        for (int i = 0; i < layout.size(); i++) {
            setItem(i, ItemStack.EMPTY);
        }
    }

    @Override
    public boolean canPlaceItem(int index, ItemStack stack) {
        if (index < 0 || index >= layout.size()) return false;
        CuriosCompat.WornSlot s = layout.get(index);
        return CuriosCompat.accepts(bot, s.slotType(), s.index(), stack);
    }

    @Override
    public boolean stillValid(Player player) {
        // The menu owns its own stillValid; the container is only reached
        // through a live bot, so it is always valid while open.
        return true;
    }
}
