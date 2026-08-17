package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.bot.VehicleDriver;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec3;

import java.util.UUID;

/**
 * Drive the vehicle the bot is piloting to a location, or follow an entity /
 * player named by {@code target}. Land, boats and helicopters only. Fails
 * clearly if the bot isn't in the driver seat, the vehicle can't be driven by
 * bots, or it has no energy. Time-boxed by {@code count} seconds (default 120).
 */
public class DriveVehicleBehavior implements Behavior {

    private static final int DEFAULT_SECONDS = 120;

    private final ProgressReport progress = new ProgressReport();
    private final VehicleDriver.State st = new VehicleDriver.State();
    private Vec3 dest;
    private String followTarget;
    private int ticks, maxTicks;
    private boolean done, failed;
    private int lastEnergyWarnTick = -1000;
    private BotPlayer owner;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        owner = bot;
        ticks = 0; done = false; failed = false;
        int c = directive.getCount();
        maxTicks = (c > 0 ? c : DEFAULT_SECONDS) * 20;
        dest = directive.hasLocation() ? new Vec3(directive.getX(), directive.getY(), directive.getZ()) : null;
        followTarget = directive.getTarget() == null ? "" : directive.getTarget().trim();
        progress.setPhase("driving");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (done) return failed ? BehaviorResult.FAILED : BehaviorResult.SUCCESS;
        ServerPlayer player = bot.getPlayer();
        Entity v = SwVehicleCompat.vehicleOf(player);
        if (v == null) return fail(bot, "not aboard a Superb Warfare vehicle (MOUNT_VEHICLE first)");
        if (!SwVehicleCompat.isDriver(player)) return fail(bot, "not in the driver seat");
        if (!SwVehicleCompat.drivable(v)) return fail(bot, SwVehicleCompat.displayName(v) + " can't be driven by bots (" + SwVehicleCompat.engineKind(v) + ")");
        if (SwVehicleCompat.hasEnergyStorage(v) && SwVehicleCompat.energy(v) <= 0) {
            if (ticks - lastEnergyWarnTick > 200) {
                lastEnergyWarnTick = ticks;
                bot.systemChat(SwVehicleCompat.displayName(v) + " has no energy — needs charging", "red");
            }
            if (ticks++ > 100) return fail(bot, "vehicle has no energy");
            return BehaviorResult.RUNNING;
        }
        Vec3 goal = resolveGoal(player.serverLevel(), player);
        if (goal == null) return fail(bot, "no destination (give x/y/z or a target to follow)");

        ticks++;
        boolean arrived = VehicleDriver.driveTo(v, st, goal, VehicleDriver.DEFAULT_ARRIVE);
        if (ticks % 40 == 0) progress.setPhase("driving " + st.lastNote);
        if (arrived && followTarget.isEmpty()) {
            progress.logEvent("Arrived at " + fmt(goal));
            bot.systemChat("Arrived at " + fmt(goal), "aqua");
            done = true;
            return BehaviorResult.SUCCESS;
        }
        if (arrived && st.lastNote.contains("not drivable")) return fail(bot, st.lastNote);
        if (ticks >= maxTicks) {
            VehicleDriver.stop(v);
            progress.logEvent("Drive time elapsed");
            done = true;
            return BehaviorResult.SUCCESS;
        }
        return BehaviorResult.RUNNING;
    }

    private Vec3 resolveGoal(ServerLevel level, ServerPlayer player) {
        if (!followTarget.isEmpty()) {
            Entity e = null;
            try { e = level.getEntity(UUID.fromString(followTarget)); } catch (IllegalArgumentException ignored) {}
            if (e == null) e = level.getServer().getPlayerList().getPlayerByName(followTarget);
            if (e == null) {
                String needle = followTarget.toLowerCase();
                double best = Double.MAX_VALUE;
                for (Entity x : level.getAllEntities()) {
                    if (x == player || x == player.getVehicle()) continue;
                    String n = x.getName().getString().toLowerCase();
                    String t = x.getType().toShortString().toLowerCase();
                    if (!n.contains(needle) && !t.contains(needle)) continue;
                    double d = x.distanceToSqr(player);
                    if (d < best) { best = d; e = x; }
                }
            }
            return e == null ? null : e.position();
        }
        return dest;
    }

    private BehaviorResult fail(BotPlayer bot, String why) {
        done = true; failed = true;
        Entity v = SwVehicleCompat.vehicleOf(bot.getPlayer());
        if (v != null) VehicleDriver.stop(v);
        progress.setFailureReason(why);
        progress.logEvent("Drive failed: " + why);
        bot.systemChat("Can't drive: " + why, "red");
        return BehaviorResult.FAILED;
    }

    private static String fmt(Vec3 p) { return (int) p.x + ", " + (int) p.y + ", " + (int) p.z; }

    @Override
    public String describeState() {
        return done ? (failed ? "Drive failed" : "Drive complete") : "Driving " + st.lastNote;
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {
        // Release the keys when interrupted so the vehicle doesn't run away.
        if (owner != null && owner.getPlayer() != null) {
            Entity v = SwVehicleCompat.vehicleOf(owner.getPlayer());
            if (v != null) VehicleDriver.stop(v);
        }
    }
}
