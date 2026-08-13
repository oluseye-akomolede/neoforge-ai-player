package com.sigmastrain.aiplayermod.client.overlay;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.network.OverlayPayloads;
import net.minecraft.client.Minecraft;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.neoforge.client.event.RenderGuiEvent;

/**
 * The tether — always visible while jacked in, overlay open or not.
 *
 * <p>Out-of-body play only works if the player can feel their abandoned
 * body: where it is, how much health it has left, and that H → Eject gets
 * them back. One line, top center, red when the body is hurting.
 */
@EventBusSubscriber(modid = AIPlayerMod.MOD_ID, value = Dist.CLIENT)
public final class JackHud {

    private JackHud() {}

    @SubscribeEvent
    public static void onRenderGui(RenderGuiEvent.Post event) {
        Minecraft mc = Minecraft.getInstance();
        var g0 = event.getGuiGraphics();

        // Control acks outlive the overlay: several buttons (jack-in
        // especially) close the panel on click, and the server's answer used
        // to arrive to a closed screen — an invisible refusal reads as "the
        // button does nothing". If the overlay isn't open, the recent ack
        // renders as a HUD toast instead.
        String ack = OverlayClientState.recentAck();
        if (!ack.isEmpty() && !(mc.screen instanceof OverlayScreen)) {
            var f = mc.font;
            int aw = f.width(ack);
            int ax = (g0.guiWidth() - aw) / 2;
            int ay = 18;
            g0.fill(ax - 4, ay - 2, ax + aw + 4, ay + 11, 0x88000000);
            g0.drawString(f, ack, ax, ay, 0xFFFFD54F);
        }

        OverlayPayloads.JackState s = OverlayClientState.jackState();
        if (!s.active()) return;

        var g = event.getGuiGraphics();
        var font = mc.font;

        float hearts = s.huskHealth() / 2f;
        String dim = s.dimension().contains(":")
                ? s.dimension().substring(s.dimension().indexOf(':') + 1) : s.dimension();
        String color = hearts <= 3 ? "§c" : hearts <= 6 ? "§e" : "§7";
        String line = "§d◈ " + s.bot() + " §8· body " + color
                + String.format("%.0f♥ ", hearts) + "§8at " + s.x() + "," + s.z()
                + " (" + dim + ") · H → eject";

        int w = font.width(line);
        int x = (g.guiWidth() - w) / 2;
        int y = 4;
        g.fill(x - 4, y - 2, x + w + 4, y + 11, 0x88000000);
        g.drawString(font, line, x, y, 0xFFFFFFFF);
    }
}
