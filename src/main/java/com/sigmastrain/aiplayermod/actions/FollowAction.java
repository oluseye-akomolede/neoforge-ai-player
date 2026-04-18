package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

public class FollowAction implements BotAction {
    private final String targetName;
    private final double followDistance;
    private final double searchRadius;
    private int ticksWithoutTarget = 0;
    private static final int GIVE_UP_TICKS = 100;

    public FollowAction(String targetName, double followDistance, double searchRadius) {
        this.targetName = targetName.toLowerCase();
        this.followDistance = followDistance;
        this.searchRadius = searchRadius;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        AABB box = player.getBoundingBox().inflate(searchRadius);

        Entity target = null;
        double closest = Double.MAX_VALUE;
        for (Entity e : player.level().getEntities(player, box)) {
            if (!(e instanceof LivingEntity)) continue;
            String type = e.getType().toShortString().toLowerCase();
            String name = e.getName().getString().toLowerCase();
            if (type.contains(targetName) || name.contains(targetName)) {
                double dist = e.distanceTo(player);
                if (dist < closest) {
                    closest = dist;
                    target = e;
                }
            }
        }

        if (target == null) {
            return ++ticksWithoutTarget > GIVE_UP_TICKS;
        }
        ticksWithoutTarget = 0;

        bot.lookAt(target.getX(), target.getEyeY(), target.getZ());

        if (closest > followDistance) {
            Vec3 dir = target.position().subtract(player.position()).normalize().scale(0.2);
            player.move(MoverType.SELF, new Vec3(dir.x, player.onGround() ? 0 : -0.08, dir.z));
        }
        return false;
    }

    @Override
    public String describe() {
        return "Follow(" + targetName + ")";
    }
}
