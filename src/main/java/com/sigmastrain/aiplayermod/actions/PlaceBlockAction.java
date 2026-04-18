package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;

public class PlaceBlockAction implements BotAction {
    private final int x, y, z;

    public PlaceBlockAction(int x, int y, int z) {
        this.x = x;
        this.y = y;
        this.z = z;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        BlockPos pos = new BlockPos(x, y, z);

        bot.lookAt(x + 0.5, y + 0.5, z + 0.5);

        ItemStack heldItem = player.getMainHandItem();
        if (!(heldItem.getItem() instanceof BlockItem blockItem)) {
            return true; // not holding a block
        }

        BlockHitResult hitResult = new BlockHitResult(
                Vec3.atCenterOf(pos), Direction.UP, pos, false);

        UseOnContext context = new UseOnContext(player, InteractionHand.MAIN_HAND, hitResult);
        blockItem.useOn(context);
        return true;
    }

    @Override
    public String describe() {
        return String.format("Place(%d, %d, %d)", x, y, z);
    }
}
