package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.phys.AABB;

import java.util.List;

/**
 * Bots are packet ghosts — they are not in {@code level.players()}, so
 * every vanilla "find the nearest player to attack" scan is blind to
 * them. Rather than widening those scans with mixins (which would also
 * pull bots into mob SPAWNING and despawn math — see the fake-player
 * spawning ruling), this pump hands targets to idle hostiles directly:
 * every second, each bot offers itself to targetless monsters nearby
 * that can see it. Vanilla attack goals take over from there.
 */
public final class BotAggro {

    private BotAggro() {}

    private static final int PERIOD_TICKS = 20;
    private static final double RADIUS = 16.0;

    private static int clock;

    public static void tick() {
        if (++clock % PERIOD_TICKS != 0) return;
        for (BotPlayer bot : BotManager.getAllBots().values()) {
            try {
                offer(bot);
            } catch (Exception e) {
                AIPlayerMod.LOGGER.debug("[aggro] pump failed for bot: {}", e.toString());
            }
        }
    }

    private static void offer(BotPlayer bot) {
        if (!bot.isAlive()) return;
        ServerPlayer p = bot.getPlayer();
        if (p.isSpectator() || p.isCreative()) return;
        List<Mob> mobs = p.serverLevel().getEntitiesOfClass(Mob.class,
                new AABB(p.blockPosition()).inflate(RADIUS),
                m -> m instanceof Enemy && m.isAlive() && m.getTarget() == null);
        for (Mob mob : mobs) {
            if (mob.getSensing().hasLineOfSight(p)) {
                mob.setTarget(p);
            }
        }
    }
}
