package com.sigmastrain.aiplayermod.client;

import com.sigmastrain.aiplayermod.bot.BotEquipmentMenu;
import com.sigmastrain.aiplayermod.client.overlay.OverlayClientState;
import com.sigmastrain.aiplayermod.network.OverlayPayloads;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.gui.screens.inventory.InventoryScreen;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Inventory;
import net.neoforged.neoforge.network.PacketDistributor;

public class BotEquipmentScreen extends AbstractContainerScreen<BotEquipmentMenu> {

    private static final ResourceLocation INVENTORY_TEXTURE =
            ResourceLocation.withDefaultNamespace("textures/gui/container/inventory.png");
    private static final ResourceLocation CONTAINER_TEXTURE =
            ResourceLocation.withDefaultNamespace("textures/gui/container/generic_54.png");

    private float xMouse;
    private float yMouse;

    // Chat-with-this-bot overlay: a natural-language ORDER lane on top of
    // the equipment view — "put your non-essentials away" typed right where
    // you are looking at the inventory in question (v8 entry point).
    private boolean chatOpen = false;
    private EditBox chatInput;

    public BotEquipmentScreen(BotEquipmentMenu menu, Inventory playerInventory, Component title) {
        super(menu, playerInventory, title);
        this.imageHeight = 262;
        this.titleLabelX = 97;
        this.titleLabelY = 8;
        this.inventoryLabelX = 8;
        this.inventoryLabelY = 170;
    }

    @Override
    protected void init() {
        super.init();
        addRenderableWidget(Button.builder(Component.literal("\ud83d\udcac"), b -> {
                    chatOpen = !chatOpen;
                    chatInput.setVisible(chatOpen);
                    if (chatOpen) setFocused(chatInput);
                })
                .bounds(leftPos + imageWidth - 22, topPos + 4, 18, 14).build());

        // The input sits INSIDE the panel and renders with it at tooltip Z
        // (live report: slot items drew over the box). addWidget = events
        // only; the render happens in our lifted pass.
        chatInput = new EditBox(font, leftPos + 12, topPos + imageHeight / 2 + 30,
                imageWidth - 24, 14, Component.literal("order"));
        chatInput.setHint(Component.literal("tell this bot what to do with its gear…"));
        chatInput.setMaxLength(300);
        chatInput.setVisible(false);
        addWidget(chatInput);

        addRenderableWidget(Button.builder(Component.literal("←"), b -> onClose())
                .bounds(leftPos + imageWidth - 42, topPos + 4, 18, 14).build());
    }

    // ESC (and ←) return to the overlay — the equipment window is a leaf
    // of the control plane, not a separate world (live report: ESC dumped
    // the player back to the game with no way back).
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
        // Fall back to the name in the window title ("<bot>'s Inventory").
        String t = getTitle().getString();
        return t.contains("'") ? t.substring(0, t.indexOf("'")) : t;
    }

    private String botDisplayName() {
        String t = getTitle().getString();
        return t.contains("'") ? t.substring(0, t.indexOf("'")) : t;
    }

    private void sendChatOrder() {
        String text = chatInput.getValue().trim();
        if (text.isEmpty()) return;
        var params = new com.google.gson.JsonObject();
        params.addProperty("text", text);
        PacketDistributor.sendToServer(new OverlayPayloads.SubmitOrder(
                botAddress(), "TEXT", params.toString()));
        chatInput.setValue("");
    }

    @Override
    public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
        if (chatOpen && getFocused() == chatInput) {
            if (keyCode == 257) { // enter sends
                sendChatOrder();
                return true;
            }
            if (keyCode == 256) { // esc closes the chat, not the screen
                chatOpen = false;
                chatInput.setVisible(false);
                return true;
            }
            // let the box eat inventory keys ('e' must type, not close)
            return chatInput.keyPressed(keyCode, scanCode, modifiers)
                    || chatInput.canConsumeInput()
                    || super.keyPressed(keyCode, scanCode, modifiers);
        }
        return super.keyPressed(keyCode, scanCode, modifiers);
    }

    @Override
    protected void renderBg(GuiGraphics guiGraphics, float partialTick, int mouseX, int mouseY) {
        int x = this.leftPos;
        int y = this.topPos;

        guiGraphics.blit(INVENTORY_TEXTURE, x, y, 0, 0, this.imageWidth, 166);
        guiGraphics.blit(CONTAINER_TEXTURE, x, y + 166, 0, 126, this.imageWidth, 96);

        // Hardpoint labels — an empty extra slot means nothing without one.
        var auxLabels = this.menu.getAuxLabels();
        for (int i = 0; i < Math.min(auxLabels.size(), this.menu.getAuxCount()); i++) {
            guiGraphics.drawString(this.font, "§8" + auxLabels.get(i),
                    x + 148, y + 26 + i * 18, 0xFF7A8B8B, false);
        }

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
        if (chatOpen) {
            // Tooltip-level Z: this overlay must beat every slot highlight.
            guiGraphics.pose().pushPose();
            guiGraphics.pose().translate(0, 0, 400);
            int x = leftPos + 6, w = imageWidth - 12;
            int y = topPos + imageHeight / 2 - 42;
            guiGraphics.fill(x, y, x + w, y + 92, 0xF0090D12);
            guiGraphics.fill(x, y, x + w, y + 1, 0xFF54E8E0);
            guiGraphics.drawString(font, "§b" + botDisplayName()
                    + " §8· plain-language orders · Enter sends", x + 6, y + 5, 0xFFDDE8E8);
            var orders = OverlayClientState.ordersFor(botDisplayName());
            int shown = 0;
            for (int i = orders.size() - 1; i >= 0 && shown < 4; i--, shown++) {
                var o = orders.get(i);
                String color = switch (o.status()) {
                    case "COMPLETED" -> "§a";
                    case "FAILED" -> "§c";
                    case "RUNNING" -> "§b";
                    default -> "§7";
                };
                String line = "§8#" + o.id() + " " + color + o.status() + " §7" + o.detail();
                if (font.width(line) > w - 16) line = font.plainSubstrByWidth(line, w - 20) + "…";
                guiGraphics.drawString(font, line, x + 6, y + 18 + shown * 11, 0xFF7A8B8B);
            }
            chatInput.render(guiGraphics, mouseX, mouseY, partialTick);
            guiGraphics.pose().popPose();
        }
        this.renderTooltip(guiGraphics, mouseX, mouseY);
    }
}
