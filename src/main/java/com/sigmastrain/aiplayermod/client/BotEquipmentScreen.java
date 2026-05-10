package com.sigmastrain.aiplayermod.client;

import com.sigmastrain.aiplayermod.bot.BotEquipmentMenu;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.gui.screens.inventory.InventoryScreen;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Inventory;

public class BotEquipmentScreen extends AbstractContainerScreen<BotEquipmentMenu> {

    private static final ResourceLocation INVENTORY_TEXTURE =
            ResourceLocation.withDefaultNamespace("textures/gui/container/inventory.png");
    private static final ResourceLocation CONTAINER_TEXTURE =
            ResourceLocation.withDefaultNamespace("textures/gui/container/generic_54.png");

    private float xMouse;
    private float yMouse;

    public BotEquipmentScreen(BotEquipmentMenu menu, Inventory playerInventory, Component title) {
        super(menu, playerInventory, title);
        this.imageHeight = 262;
        this.titleLabelX = 97;
        this.titleLabelY = 8;
        this.inventoryLabelX = 8;
        this.inventoryLabelY = 170;
    }

    @Override
    protected void renderBg(GuiGraphics guiGraphics, float partialTick, int mouseX, int mouseY) {
        int x = this.leftPos;
        int y = this.topPos;

        guiGraphics.blit(INVENTORY_TEXTURE, x, y, 0, 0, this.imageWidth, 166);
        guiGraphics.blit(CONTAINER_TEXTURE, x, y + 166, 0, 126, this.imageWidth, 96);

        int entityId = this.menu.getBotEntityId();
        if (entityId >= 0 && this.minecraft != null && this.minecraft.level != null) {
            var entity = this.minecraft.level.getEntity(entityId);
            if (entity instanceof LivingEntity living) {
                InventoryScreen.renderEntityInInventoryFollowsMouse(
                        guiGraphics,
                        x + 26, y + 8,
                        x + 75, y + 78,
                        30, 0.0625F,
                        this.xMouse, this.yMouse,
                        living
                );
            }
        }
    }

    @Override
    public void render(GuiGraphics guiGraphics, int mouseX, int mouseY, float partialTick) {
        this.xMouse = (float) mouseX;
        this.yMouse = (float) mouseY;
        super.render(guiGraphics, mouseX, mouseY, partialTick);
        this.renderTooltip(guiGraphics, mouseX, mouseY);
    }
}
