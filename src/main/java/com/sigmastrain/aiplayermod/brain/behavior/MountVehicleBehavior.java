package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec3;

import java.util.Map;
import java.util.UUID;

/**
 * Board a Superb Warfare vehicle.
 *
 * <p>{@code target}: a vehicle UUID, an SW vehicle-type or entity-name
 * substring ("tank", "lav", "m1a2", "ah6"), or empty for the nearest vehicle
 * within {@code radius} (default 32). {@code extra.seat} picks a seat index;
 * {@code extra.role=gunner} prefers the first armed non-driver seat; otherwise
 * the driver seat (0) is preferred when free. The bot steps to within reach
 * (teleport, like every other bot approach) and boards via startRiding —
 * SW's interact path rejects fake players.
 */
public class MountVehicleBehavior implements Behavior {

    private static final int DEFAULT_RADIUS = 32;

    private final ProgressReport progress = new ProgressReport();
    private String target;
    private int radius;
    private int wantSeat = -1;
    private boolean gunner;
    private int waitTicks, ticks;
    private boolean done;
    private boolean failed;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        target = directive.getTarget() == null ? "" : directive.getTarget().trim();
        radius = directive.getRadius() > 0 && directive.getRadius() != 256 ? directive.getRadius() : DEFAULT_RADIUS;
        Map<String, String> extra = directive.getExtra();
        try { wantSeat = Integer.parseInt(extra.getOrDefault("seat", "-1").trim()); } catch (NumberFormatException e) { wantSeat = -1; }
        gunner = "gunner".equalsIgnoreCase(extra.getOrDefault("role", ""));
        int w = 0;
        try { w = Integer.parseInt(extra.getOrDefault("wait", "0").trim()); } catch (NumberFormatException e) { w = 0; }
        waitTicks = Math.max(0, Math.min(300, w)) * 20;   // keep looking this long before giving up
        ticks = 0;
        done = false; failed = false;
        progress.setPhase("locating vehicle");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (done) return failed ? BehaviorResult.FAILED : BehaviorResult.SUCCESS;
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        if (!SwVehicleCompat.isAvailable()) return fail(bot, "Superb Warfare vehicles unavailable");

        Entity v = resolve(level, player);
        if (v == null) {
            if (ticks++ < waitTicks) {
                if (ticks == 1) progress.setPhase("waiting for a vehicle");
                return BehaviorResult.RUNNING;
            }
            return fail(bot, "no vehicle found" + (target.isEmpty() ? "" : " matching '" + target + "'") + " within " + radius);
        }
        if (SwVehicleCompat.isWreck(v)) return fail(bot, SwVehicleCompat.displayName(v) + " is wrecked");

        // Step next to it (bots approach by teleport everywhere else too).
        if (player.distanceTo(v) > 4.0) {
            Vec3 p = v.position();
            Vec3 dir = player.position().subtract(p);
            dir = dir.length() > 0.1 ? dir.normalize() : new Vec3(1, 0, 0);
            bot.teleport(p.x + dir.x * 2.5, p.y, p.z + dir.z * 2.5);
        }

        int seat = wantSeat;
        if (seat < 0) seat = pickSeat(v);
        String err = SwVehicleCompat.board(player, v, seat);
        if (err != null) return fail(bot, err);

        int got = SwVehicleCompat.seatIndex(v, player);
        String name = SwVehicleCompat.displayName(v);
        progress.putResult("vehicle", v.getUUID().toString());
        progress.putResult("seat", String.valueOf(got));
        progress.logEvent("Boarded " + name + " seat " + got);
        bot.systemChat("Boarded " + name + " (seat " + got + (got == 0 ? ", driver" : "")
                + (SwVehicleCompat.hasWeapon(v, got) ? ", " + SwVehicleCompat.weaponName(v, got) : "") + ")", "aqua");
        AIPlayerMod.LOGGER.info("[{}] boarded {} seat {}", player.getName().getString(), name, got);
        done = true;
        return BehaviorResult.SUCCESS;
    }

    private int pickSeat(Entity v) {
        int max = SwVehicleCompat.maxPassengers(v);
        var ps = SwVehicleCompat.orderedPassengers(v);
        java.util.function.IntPredicate free = i -> i >= ps.size() || ps.get(i) == null;
        if (gunner) {
            for (int i = 1; i < max; i++) if (free.test(i) && SwVehicleCompat.hasWeapon(v, i)) return i;
        }
        if (free.test(0)) return 0;
        for (int i = 1; i < max; i++) if (free.test(i) && SwVehicleCompat.hasWeapon(v, i)) return i;
        return SwVehicleCompat.firstFreeSeat(v);
    }

    private Entity resolve(ServerLevel level, ServerPlayer player) {
        if (!target.isEmpty()) {
            try {
                Entity byId = level.getEntity(UUID.fromString(target));
                if (SwVehicleCompat.isVehicle(byId)) return byId;
            } catch (IllegalArgumentException ignored) {
            }
            String needle = target.toLowerCase();
            return SwVehicleCompat.nearestVehicle(level, player.position(), radius, e -> {
                String type = e.getType().toShortString().toLowerCase();
                String name = e.getName().getString().toLowerCase();
                String cls = SwVehicleCompat.typeName(e).toLowerCase();
                return type.contains(needle) || name.contains(needle) || cls.contains(needle);
            });
        }
        return SwVehicleCompat.nearestVehicle(level, player.position(), radius, null);
    }

    private BehaviorResult fail(BotPlayer bot, String why) {
        done = true; failed = true;
        progress.setFailureReason(why);
        progress.logEvent("Mount failed: " + why);
        bot.systemChat("Can't board: " + why, "red");
        return BehaviorResult.FAILED;
    }

    @Override
    public String describeState() {
        return done ? (failed ? "Mount failed" : "Aboard vehicle") : "Boarding vehicle" + (target.isEmpty() ? "" : " '" + target + "'");
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
