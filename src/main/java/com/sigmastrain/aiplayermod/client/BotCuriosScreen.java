package com.sigmastrain.aiplayermod.client;

import com.sigmastrain.aiplayermod.bot.BotCuriosMenu;
import com.sigmastrain.aiplayermod.network.OverlayPayloads;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.inventory.Slot;
import net.neoforged.neoforge.network.PacketDistributor;

/**
 * A bot's 48 curios slots as a grid. Reached from the equipment window's ◈
 * button. The ← header returns to the equipment window; ESC returns to the
 * overlay. Slot types are identified on hover — 48 tight slots have no room
 * for a label under each, so the type name rides the tooltip instead.
 */
public class BotCuriosScreen extends AbstractContainerScreen<BotCuriosMenu> {

    private static final ResourceLocation INVENTORY_TEXTURE =
            ResourceLocation.withDefaultNamespace("textures/gui/container/inventory.png");
    private static final ResourceLocation CONTAINER_TEXTURE =
            ResourceLocation.withDefaultNamespace("textures/gui/container/generic_54.png");

    // Mirrors BotCuriosMenu's layout constants so the background lines up.
    private static final int COLS = 8;
    private static final int GRID_X = 8;
    private static final int GRID_Y = 20;

    public BotCuriosScreen(BotCuriosMenu menu, Inventory playerInventory, Component title) {
        super(menu, playerInventory, title);
        int rows = (menu.getCurioCount() + COLS - 1) / COLS;
        int playerTop = GRID_Y + rows * 18 + 14;
        this.imageHeight = playerTop + 58 + 18 + 7; // main + hotbar + margin
        this.titleLabelX = 8;
        this.titleLabelY = 6;
        this.inventoryLabelX = 8;
        this.inventoryLabelY = playerTop - 11;
    }

    @Override
    protected void init() {
        super.init();
        // ← returns to the equipment window (this is a leaf of that screen).
        addRenderableWidget(Button.builder(Component.literal("←"), b ->
                        PacketDistributor.sendToServer(new OverlayPayloads.OpenEquipment(botAddress())))
                .bounds(leftPos + imageWidth - 42, topPos + 4, 18, 14).build());
    }

    // ESC dumps the player back to the overlay, same as the equipment window.
    @Override
    public void onClose() {
        super.onClose();
        if (this.minecraft != null) {
            this.minecraft.setScreen(
                    new com.sigmastrain.aiplayermod.client.overlay.OverlayScreen());
        }
    }

    private String botAddress() {
        int entityId = this.menu.getBotEntityId();
        if (entityId >= 0 && this.minecraft != null && this.minecraft.level != null) {
            var entity = this.minecraft.level.getEntity(entityId);
            if (entity != null) return entity.getUUID().toString();
        }
        String t = getTitle().getString();
        return t.contains("'") ? t.substring(0, t.indexOf("'")) : t;
    }

    @Override
    protected void renderBg(GuiGraphics guiGraphics, float partialTick, int mouseX, int mouseY) {
        int x = this.leftPos;
        int y = this.topPos;
        int rows = (this.menu.getCurioCount() + COLS - 1) / COLS;
        int playerTop = GRID_Y + rows * 18 + 14;

        // Curios grid: generic container texture (title bar + N rows) extended
        // down to the inventory label so the gap stays filled.
        guiGraphics.blit(CONTAINER_TEXTURE, x, y + 3, 0, 0, this.imageWidth, 17 + rows * 18 + 14);
        // Player inventory + hotbar: the main+hotbar slice of inventory.png.
        guiGraphics.blit(INVENTORY_TEXTURE, x, y + playerTop, 0, 84, this.imageWidth, 82);
    }

    @Override
    public void render(GuiGraphics guiGraphics, int mouseX, int mouseY, float partialTick) {
        super.render(guiGraphics, mouseX, mouseY, partialTick);
        // Slot-type name on hover — a 48-slot grid has no room for a per-slot
        // label, so the type rides a tooltip above the item's own tooltip.
        int n = this.menu.getCurioCount();
        var labels = this.menu.getCurioLabels();
        for (Slot slot : this.menu.slots) {
            if (slot.index >= n || !isHovering(slot.x, slot.y, 16, 16, mouseX, mouseY)) continue;
            String label = slot.index < labels.size() ? labels.get(slot.index) : "?";
            guiGraphics.renderTooltip(this.font, Component.literal("§b§o" + label),
                    mouseX + 12, mouseY - 12 - this.font.lineHeight - 2);
            break;
        }
    }
}
