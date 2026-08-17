package com.sigmastrain.aiplayermod.client;

import com.sigmastrain.aiplayermod.bot.BotVehicleMenu;
import com.sigmastrain.aiplayermod.bot.VehicleContainer;
import com.sigmastrain.aiplayermod.network.OverlayPayloads;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.player.Inventory;
import net.neoforged.neoforge.network.PacketDistributor;

/**
 * A vehicle's hold, one page (≤54 slots) at a time. ◀ ▶ reopen the menu on
 * the neighbouring page (a fresh open is the only way to change slot count
 * safely); ← returns to the overlay.
 */
public class BotVehicleScreen extends AbstractContainerScreen<BotVehicleMenu> {

    private static final ResourceLocation INVENTORY_TEXTURE =
            ResourceLocation.withDefaultNamespace("textures/gui/container/inventory.png");
    private static final ResourceLocation CONTAINER_TEXTURE =
            ResourceLocation.withDefaultNamespace("textures/gui/container/generic_54.png");

    private static final int GRID_Y = 18;

    public BotVehicleScreen(BotVehicleMenu menu, Inventory playerInventory, Component title) {
        super(menu, playerInventory, title);
        int rows = Math.max(1, menu.rows());
        int playerTop = GRID_Y + rows * 18 + 14;
        this.imageHeight = playerTop + 58 + 18 + 7;
        this.titleLabelX = 8;
        this.titleLabelY = 6;
        this.inventoryLabelX = 8;
        this.inventoryLabelY = playerTop - 11;
    }

    @Override
    protected void init() {
        super.init();
        int pages = VehicleContainer.pages(menu.getTotalSlots());
        int page = menu.getPage();
        String bot = botAddress();
        if (pages > 1) {
            addRenderableWidget(Button.builder(Component.literal("◀"), b -> {
                        if (page > 0) PacketDistributor.sendToServer(
                                new OverlayPayloads.VehicleOp(bot, "open_inventory", String.valueOf(page - 1)));
                    }).bounds(leftPos + imageWidth - 82, topPos + 4, 18, 14).build())
                    .active = page > 0;
            addRenderableWidget(Button.builder(Component.literal("▶"), b -> {
                        if (page < pages - 1) PacketDistributor.sendToServer(
                                new OverlayPayloads.VehicleOp(bot, "open_inventory", String.valueOf(page + 1)));
                    }).bounds(leftPos + imageWidth - 62, topPos + 4, 18, 14).build())
                    .active = page < pages - 1;
        }
        addRenderableWidget(Button.builder(Component.literal("←"), b -> onClose())
                .bounds(leftPos + imageWidth - 42, topPos + 4, 18, 14).build());
    }

    @Override
    public void onClose() {
        super.onClose();
        if (this.minecraft != null) {
            this.minecraft.setScreen(new com.sigmastrain.aiplayermod.client.overlay.OverlayScreen());
        }
    }

    private String botAddress() {
        int entityId = this.menu.getBotEntityId();
        if (entityId >= 0 && this.minecraft != null && this.minecraft.level != null) {
            var entity = this.minecraft.level.getEntity(entityId);
            if (entity != null) return entity.getUUID().toString();
        }
        return this.menu.getBotName();
    }

    @Override
    protected void renderBg(GuiGraphics g, float partialTick, int mouseX, int mouseY) {
        int x = this.leftPos, y = this.topPos;
        int rows = Math.max(1, this.menu.rows());
        int playerTop = GRID_Y + rows * 18 + 14;
        g.blit(CONTAINER_TEXTURE, x, y + 1, 0, 0, this.imageWidth, 17 + rows * 18 + 14);
        g.blit(INVENTORY_TEXTURE, x, y + playerTop, 0, 84, this.imageWidth, 82);
    }

    @Override
    protected void renderLabels(GuiGraphics g, int mouseX, int mouseY) {
        int pages = VehicleContainer.pages(menu.getTotalSlots());
        String t = menu.getVehicleName() + (pages > 1 ? "  §7" + (menu.getPage() + 1) + "/" + pages : "");
        g.drawString(this.font, t, this.titleLabelX, this.titleLabelY, 4210752, false);
        g.drawString(this.font, this.playerInventoryTitle, this.inventoryLabelX, this.inventoryLabelY, 4210752, false);
    }
}
