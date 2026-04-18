package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.block.state.BlockState;

public class MineBlockAction implements BotAction {
    private final int x, y, z;
    private int breakProgress = 0;
    private boolean started = false;

    public MineBlockAction(int x, int y, int z) {
        this.x = x;
        this.y = y;
        this.z = z;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockPos pos = new BlockPos(x, y, z);
        BlockState state = level.getBlockState(pos);

        if (state.isAir()) {
            return true;
        }

        bot.lookAt(x + 0.5, y + 0.5, z + 0.5);

        float hardness = state.getDestroySpeed(level, pos);
        if (hardness < 0) {
            return true; // unbreakable
        }

        float speed = player.getMainHandItem().getDestroySpeed(state);
        float progress = speed / hardness / 30.0f;
        breakProgress++;

        if (breakProgress * progress >= 1.0f || hardness == 0) {
            level.destroyBlock(pos, true, player);
            return true;
        }

        return false;
    }

    @Override
    public String describe() {
        return String.format("Mine(%d, %d, %d)", x, y, z);
    }
}
