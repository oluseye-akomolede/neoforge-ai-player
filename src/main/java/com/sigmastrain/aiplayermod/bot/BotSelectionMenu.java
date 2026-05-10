package com.sigmastrain.aiplayermod.bot;

import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.Style;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.SimpleContainer;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.inventory.MenuType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.core.component.DataComponents;
import net.minecraft.world.item.component.ResolvableProfile;
import com.mojang.authlib.GameProfile;

import java.util.List;

public class BotSelectionMenu extends AbstractContainerMenu {

    private final List<BotPlayer> bots;
    private final ServerPlayer viewer;
    private final SimpleContainer container;

    public BotSelectionMenu(int containerId, Inventory playerInventory, List<BotPlayer> bots) {
        super(MenuType.GENERIC_9x1, containerId);
        this.bots = bots;
        this.viewer = (ServerPlayer) playerInventory.player;
        this.container = new SimpleContainer(9);

        for (int i = 0; i < 9; i++) {
            if (i < bots.size()) {
                BotPlayer bot = bots.get(i);
                String name = bot.getPlayer().getName().getString();
                ItemStack head = new ItemStack(Items.PLAYER_HEAD);
                head.set(DataComponents.PROFILE, new ResolvableProfile(
                        new GameProfile(bot.getPlayer().getUUID(), name)));
                head.set(DataComponents.CUSTOM_NAME,
                        Component.literal(name).withStyle(Style.EMPTY.withItalic(false).withBold(true)));
                container.setItem(i, head);
            } else {
                ItemStack pane = new ItemStack(Items.GRAY_STAINED_GLASS_PANE);
                pane.set(DataComponents.CUSTOM_NAME,
                        Component.literal(" ").withStyle(Style.EMPTY.withItalic(false)));
                container.setItem(i, pane);
            }
            addSlot(new Slot(container, i, 8 + i * 18, 18) {
                @Override
                public boolean mayPlace(ItemStack stack) { return false; }
                @Override
                public boolean mayPickup(Player player) { return false; }
            });
        }

        for (int row = 0; row < 3; row++) {
            for (int col = 0; col < 9; col++) {
                addSlot(new Slot(playerInventory, col + row * 9 + 9, 8 + col * 18, 51 + row * 18));
            }
        }
        for (int col = 0; col < 9; col++) {
            addSlot(new Slot(playerInventory, col, 8 + col * 18, 109));
        }
    }

    @Override
    public void clicked(int slotId, int button, ClickType clickType, Player player) {
        if (slotId >= 0 && slotId < bots.size() && player instanceof ServerPlayer sp) {
            BotPlayer selected = bots.get(slotId);
            String botName = selected.getPlayer().getName().getString();
            int entityId = selected.getPlayer().getId();
            sp.closeContainer();
            sp.openMenu(new SimpleMenuProvider(
                    (id, inv, p) -> new BotEquipmentMenu(id, inv, selected.getPlayer().getInventory(), entityId),
                    Component.literal(botName + "'s Inventory")
            ), buf -> buf.writeInt(entityId));
            return;
        }
        super.clicked(slotId, button, clickType, player);
    }

    @Override
    public ItemStack quickMoveStack(Player player, int index) {
        return ItemStack.EMPTY;
    }

    @Override
    public boolean stillValid(Player player) {
        return true;
    }
}
