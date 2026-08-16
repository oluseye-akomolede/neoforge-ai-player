package com.sigmastrain.aiplayermod.client.overlay;

import com.mojang.blaze3d.platform.InputConstants;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.RegisterKeyMappingsEvent;
import net.neoforged.neoforge.network.PacketDistributor;
import org.lwjgl.glfw.GLFW;

/**
 * The mark-block hotkey. Default M — "mark".
 *
 * <p>Tap it while looking at a block and a raycast from the view (up to 64
 * blocks) marks that block: it glows white client-side (see
 * {@link MarkedBlockRenderer}) and the position is sent to the server's
 * {@code MarkStore}, where the agent resolves it as "the marked area" for any
 * location-taking directive (goto, area loot, wide search).
 */
@EventBusSubscriber(modid = AIPlayerMod.MOD_ID, bus = EventBusSubscriber.Bus.MOD, value = Dist.CLIENT)
public final class MarkBlockKeybind {

    private MarkBlockKeybind() {}

    public static final KeyMapping MARK_BLOCK = new KeyMapping(
            "key.aiplayermod.mark_block",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_M,
            "key.categories.aiplayermod");

    @SubscribeEvent
    public static void onRegisterKeys(RegisterKeyMappingsEvent event) {
        event.register(MARK_BLOCK);
    }

    /** Game-bus tick handler, client dist only. */
    @EventBusSubscriber(modid = AIPlayerMod.MOD_ID, value = Dist.CLIENT)
    public static final class Tick {
        @SubscribeEvent
        public static void onClientTick(ClientTickEvent.Post event) {
            Minecraft mc = Minecraft.getInstance();
            while (MARK_BLOCK.consumeClick()) {
                if (mc.player == null || mc.level == null) continue;
                HitResult hit = mc.player.pick(64.0, 1.0f, false);
                if (!(hit instanceof BlockHitResult bhr)) continue;

                var pos = bhr.getBlockPos();
                String dim = mc.level.dimension().location().toString();
                MarkedBlockRenderer.setMark(pos, dim);
                PacketDistributor.sendToServer(new com.sigmastrain.aiplayermod.network
                        .OverlayPayloads.MarkBlock(pos.getX(), pos.getY(), pos.getZ()));
            }
        }
    }
}
