package com.sigmastrain.aiplayermod.client.overlay;

import com.mojang.blaze3d.platform.InputConstants;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.RegisterKeyMappingsEvent;
import org.lwjgl.glfw.GLFW;

/**
 * The overlay hotkey. Default H — "hive".
 *
 * <p>Tap to latch the overlay open; hold and release to peek (the screen
 * closes itself when the key is released after a long press — that logic
 * lives in {@link OverlayScreen#keyReleased}).
 */
@EventBusSubscriber(modid = AIPlayerMod.MOD_ID, bus = EventBusSubscriber.Bus.MOD, value = Dist.CLIENT)
public final class OverlayKeybind {

    private OverlayKeybind() {}

    public static final KeyMapping OPEN_OVERLAY = new KeyMapping(
            "key.aiplayermod.overlay",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_H,
            "key.categories.aiplayermod");

    @SubscribeEvent
    public static void onRegisterKeys(RegisterKeyMappingsEvent event) {
        event.register(OPEN_OVERLAY);
    }

    /** Game-bus tick handler, client dist only. */
    @EventBusSubscriber(modid = AIPlayerMod.MOD_ID, value = Dist.CLIENT)
    public static final class Tick {
        @SubscribeEvent
        public static void onClientTick(ClientTickEvent.Post event) {
            Minecraft mc = Minecraft.getInstance();
            while (OPEN_OVERLAY.consumeClick()) {
                if (mc.player != null && mc.screen == null) {
                    mc.setScreen(new OverlayScreen());
                }
            }
        }

        /**
         * While jacked in, E means the overlay, not the bare spectator
         * inventory — the overlay IS your inventory out there (the bot's
         * vault, the channel, the fabric).
         */
        @SubscribeEvent
        public static void onScreenOpening(net.neoforged.neoforge.client.event.ScreenEvent.Opening event) {
            if (OverlayClientState.isJackedIn()
                    && event.getNewScreen() instanceof net.minecraft.client.gui.screens.inventory.InventoryScreen
                    && !(event.getCurrentScreen() instanceof OverlayScreen)) {
                event.setNewScreen(new OverlayScreen());
            }
        }
    }
}
