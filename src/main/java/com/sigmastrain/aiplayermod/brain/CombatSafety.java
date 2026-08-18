package com.sigmastrain.aiplayermod.brain;

import com.sigmastrain.aiplayermod.bot.BotManager;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.phys.Vec3;

/**
 * Friendly-fire geometry. A bot must never put a real player in the path or the
 * blast of its own weapon — the incident that motivated this was a vehicle
 * cannon whose shell exploded next to its owner and killed him. Combat already
 * refuses to <em>target</em> players; this refuses to <em>fire</em> when a
 * player would be caught anyway.
 */
public final class CombatSafety {

    private CombatSafety() {}

    /**
     * True if firing from {@code from} toward {@code aim} would endanger any
     * real (non-bot) player: one standing within {@code blastRadius} of the
     * impact point, or within {@code lineClearance} of the line of fire between
     * the shooter and the aim point (so a player between the bot and its target
     * is never shot through).
     */
    public static boolean firingEndangersPlayer(ServerLevel level, Vec3 from, Vec3 aim,
                                                double blastRadius, double lineClearance) {
        double reach = from.distanceTo(aim) + blastRadius;
        double reachSq = reach * reach;
        for (ServerPlayer p : level.players()) {
            if (BotManager.isBot(p) || p.isSpectator() || p.isCreative()) continue;
            Vec3 pos = p.position().add(0, p.getBbHeight() * 0.5, 0);
            if (pos.distanceToSqr(aim) <= blastRadius * blastRadius) return true;
            if (pos.distanceToSqr(from) > reachSq) continue;
            if (distanceToSegmentSq(pos, from, aim) <= lineClearance * lineClearance) return true;
        }
        return false;
    }

    /** Blast radius to assume for an SW/vehicle weapon by its name. */
    public static double blastFor(String weapon) {
        String w = weapon == null ? "" : weapon.toLowerCase(java.util.Locale.ROOT);
        if (w.contains("cannon") || w.contains("main") || w.contains("missile") || w.contains("rocket")
                || w.contains("bomb") || w.contains("artillery") || w.contains("shell")) return 8.0;
        if (w.contains("laser") || w.contains("prism") || w.contains("waveforce")) return 4.0;
        return 2.0; // machine guns etc.
    }

    private static double distanceToSegmentSq(Vec3 p, Vec3 a, Vec3 b) {
        Vec3 ab = b.subtract(a);
        double len2 = ab.lengthSqr();
        if (len2 < 1.0e-6) return p.distanceToSqr(a);
        double t = Math.max(0, Math.min(1, p.subtract(a).dot(ab) / len2));
        Vec3 proj = a.add(ab.scale(t));
        return p.distanceToSqr(proj);
    }
}
