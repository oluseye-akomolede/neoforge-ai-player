package com.sigmastrain.aiplayermod.client.overlay;

import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphics;

/**
 * Extension seam: other mods mount views into the bot overlay, making it
 * the single control plane (design ruling: hive functions live IN the bot
 * window, not in parallel screens). Implementations draw into the panel
 * region they are handed and receive raw mouse events while active.
 */
public interface OverlayTab {

    /** Tab strip label, e.g. "Hive". */
    String label();

    /** Called when the tab is switched to — request fresh state here. */
    default void onOpen() {}

    /**
     * Draw the tab's content. The region is the overlay panel below the
     * tab strip: {@code (px, py)} top-left, {@code pw × ph} pixels.
     */
    void render(GuiGraphics g, Font font, int px, int py, int pw, int ph,
                int mouseX, int mouseY);

    /** @return true if the click was consumed. */
    default boolean mouseClicked(double mouseX, double mouseY, int button) {
        return false;
    }

    default boolean mouseScrolled(double mouseX, double mouseY, double dx, double dy) {
        return false;
    }

    /**
     * @return true to consume the key. Return true while the tab holds a
     * focused text field so overlay hotkeys can never fire mid-typing.
     */
    default boolean keyPressed(int keyCode, int scanCode, int modifiers) {
        return false;
    }

    default boolean charTyped(char chr, int modifiers) {
        return false;
    }
}
