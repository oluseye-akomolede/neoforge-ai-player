package com.sigmastrain.aiplayermod.client.overlay;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.client.Minecraft;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.neoforge.client.event.ViewportEvent;

/**
 * Free-look while jacked in.
 *
 * <p>Vanilla spectate copies the CAMERA ENTITY's rotation every frame, so a
 * jacked player sees exactly where the bot's pathfinding happens to point
 * its head — mostly the ground. The traveler's own mouse still rotates
 * their (bodiless) player entity though; this event swaps those angles in
 * at render time. The camera stays anchored in the bot's eyes; where you
 * LOOK from there is yours.
 */
@EventBusSubscriber(modid = AIPlayerMod.MOD_ID, value = Dist.CLIENT)
public final class JackFreeLook {

    private JackFreeLook() {}

    @SubscribeEvent
    public static void onComputeCameraAngles(ViewportEvent.ComputeCameraAngles event) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.getCameraEntity() == mc.player) return;
        if (!OverlayClientState.isJackedIn()) return;

        float partial = (float) event.getPartialTick();
        event.setYaw(mc.player.getViewYRot(partial));
        event.setPitch(mc.player.getViewXRot(partial));
    }
}
