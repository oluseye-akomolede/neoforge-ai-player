package com.sigmastrain.aiplayermod.client.overlay;

import com.mojang.blaze3d.vertex.PoseStack;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.LevelRenderer;
import net.minecraft.client.renderer.RenderType;
import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.AABB;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.neoforge.client.event.RenderLevelStageEvent;

/**
 * Draws the white "marked block" outline — the in-world feedback for the mark
 * hotkey. A single persistent wireframe box, depth-tested so it hugs the block
 * and is occluded by walls like the vanilla block highlight. Cleared only by a
 * fresh mark (client state, not synced back from the server).
 */
@EventBusSubscriber(modid = AIPlayerMod.MOD_ID, value = Dist.CLIENT)
public final class MarkedBlockRenderer {

    private MarkedBlockRenderer() {}

    private static BlockPos markedPos;
    private static String markedDimension;

    public static void setMark(BlockPos pos, String dimension) {
        markedPos = pos;
        markedDimension = dimension;
    }

    @SubscribeEvent
    public static void onRenderLevel(RenderLevelStageEvent event) {
        if (event.getStage() != RenderLevelStageEvent.Stage.AFTER_TRANSLUCENT_BLOCKS) return;
        BlockPos pos = markedPos;
        if (pos == null) return;

        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.level == null) return;
        if (markedDimension != null
                && !markedDimension.equals(mc.level.dimension().location().toString())) return;

        var cam = event.getCamera();
        var source = mc.renderBuffers().bufferSource();
        var vc = source.getBuffer(RenderType.lines());

        PoseStack pose = event.getPoseStack();
        pose.pushPose();
        pose.translate(-cam.getPosition().x, -cam.getPosition().y, -cam.getPosition().z);
        AABB box = new AABB(pos).inflate(0.002);
        LevelRenderer.renderLineBox(pose, vc, box, 1.0f, 1.0f, 1.0f, 0.9f);
        pose.popPose();

        source.endBatch(RenderType.lines());
    }
}
