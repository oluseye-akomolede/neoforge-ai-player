package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat;
import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat.EngineKind;
import net.minecraft.util.Mth;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec3;

/**
 * Steers a Superb Warfare vehicle toward a point using only the inputs a
 * player's keys would set. Land/boat: yaw error → left/right + forward (reverse
 * + turn when the target is behind); helicopter: yaw via mouse input, altitude
 * via up/down, forward when aligned. Fixed-wing is not driven (board/gun only).
 *
 * <p>The turn direction convention is learned, not assumed: if steering "left"
 * for a few ticks makes the heading error grow, the sign flips. That keeps the
 * controller correct across SW's engine implementations without hard-coding
 * their yaw handling.
 */
public final class VehicleDriver {

    private VehicleDriver() {}

    /** Per-driver memory. Keep one per bot while a drive is active. */
    public static final class State {
        int turnSign = 1;
        double lastAbsErr = Double.NaN;
        int ticks;
        boolean turningLast;
        public String lastNote = "";
        // Stuck recovery: sample position every 20 ticks; if we're pushing
        // forward and barely moved, back out for a while (turning the other
        // way), then try again.
        Vec3 samplePos;
        int sampleTick;
        int reverseUntil = -1;
        int stuckCount;
    }

    private static final int SAMPLE_TICKS = 20;
    private static final double STUCK_MOVE = 0.6;      // blocks per sample window
    private static final int REVERSE_TICKS = 40;

    public static final double DEFAULT_ARRIVE = 4.0;
    public static final double HELI_HOVER_ABOVE = 6.0;

    /**
     * One control tick. Returns true when arrived (inputs cleared).
     * Non-drivable engines return true immediately with a note.
     */
    public static boolean driveTo(Entity v, State st, Vec3 target, double arriveRadius) {
        EngineKind kind = SwVehicleCompat.engineKind(v);
        st.ticks++;
        switch (kind) {
            case LAND, BOAT -> { return steerSurface(v, st, target, arriveRadius); }
            case HELI -> { return steerHeli(v, st, target, arriveRadius); }
            default -> {
                SwVehicleCompat.clearInputs(v);
                st.lastNote = "vehicle is not drivable by bots (" + kind + ")";
                return true;
            }
        }
    }

    /** Stop everything (release all keys). */
    public static void stop(Entity v) {
        SwVehicleCompat.clearInputs(v);
    }

    static double headingError(Entity v, Vec3 target) {
        double dx = target.x - v.getX();
        double dz = target.z - v.getZ();
        double desired = Math.toDegrees(Math.atan2(-dx, dz));
        return Mth.wrapDegrees(desired - v.getYRot());
    }

    static double horizontalDistance(Entity v, Vec3 target) {
        double dx = target.x - v.getX(), dz = target.z - v.getZ();
        return Math.sqrt(dx * dx + dz * dz);
    }

    private static void learnTurnSign(State st, double absErr, boolean turning) {
        if (turning && st.turningLast && !Double.isNaN(st.lastAbsErr) && st.ticks % 10 == 0) {
            if (absErr > st.lastAbsErr + 4.0) {
                st.turnSign = -st.turnSign;   // steering the wrong way — flip
                st.lastNote = "flipped steering sign";
            }
            st.lastAbsErr = absErr;
        } else if (st.ticks % 10 == 0) {
            st.lastAbsErr = absErr;
        }
        st.turningLast = turning;
    }

    /** Horizontal speed in blocks/tick. */
    static double speed(Entity v) {
        Vec3 d = v.getDeltaMovement();
        return Math.sqrt(d.x * d.x + d.z * d.z);
    }

    private static boolean steerSurface(Entity v, State st, Vec3 target, double arriveRadius) {
        double dist = horizontalDistance(v, target);
        double spd = speed(v);
        if (dist <= arriveRadius) {
            // Hold the brake until we've actually stopped — SW power decays
            // slowly on release, so a coasting vehicle overshoots by tens of blocks.
            if (spd > 0.08) {
                SwVehicleCompat.setInputs(v, false, false, false, false, true, false, false);
                st.lastNote = String.format("braking at target (%.2f b/t)", spd);
                return false;
            }
            SwVehicleCompat.clearInputs(v);
            st.lastNote = "arrived";
            return true;
        }
        // Approach: stop accelerating inside the braking envelope and brake hard
        // when still fast close in. ~1 block of stopping distance per 0.05 b/t.
        double brakeDist = 6 + spd * 20;
        boolean closeIn = dist < brakeDist;
        double err = headingError(v, target);
        double absErr = Math.abs(err);
        boolean turning = absErr > 8;
        learnTurnSign(st, absErr, turning);

        double signed = err * st.turnSign;
        boolean left = turning && signed < 0;
        boolean right = turning && signed > 0;

        // Stuck detection while pushing forward.
        if (st.samplePos == null || st.ticks - st.sampleTick >= SAMPLE_TICKS) {
            if (st.samplePos != null && st.reverseUntil < st.ticks) {
                double moved = v.position().distanceTo(st.samplePos);
                if (moved < STUCK_MOVE) {
                    st.stuckCount++;
                    st.reverseUntil = st.ticks + REVERSE_TICKS + Math.min(st.stuckCount, 4) * 20;
                    st.lastNote = "stuck — reversing";
                } else {
                    st.stuckCount = 0;
                }
            }
            st.samplePos = v.position();
            st.sampleTick = st.ticks;
        }
        if (st.ticks < st.reverseUntil) {
            // Back out, steering the opposite way so we swing clear of the obstacle.
            SwVehicleCompat.setInputs(v, false, true, right, left, false, false, false);
            st.lastNote = String.format("reversing (%d) dist=%.1f", st.reverseUntil - st.ticks, dist);
            return false;
        }

        boolean behind = absErr > 100;
        boolean forward = !behind && (absErr < 90 || dist > 12) && !closeIn;
        boolean back = behind && dist < 25;          // reverse-turn when target is behind and close
        boolean brake = closeIn && spd > 0.15;
        boolean sprint = forward && absErr < 20 && dist > 30;
        // When reversing, steering geometry inverts on wheels/tracks.
        if (back) { boolean t = left; left = right; right = t; forward = false; }
        SwVehicleCompat.setInputs(v, forward, back, left, right, brake, false, sprint);
        st.lastNote = String.format("dist=%.1f err=%.0f spd=%.2f%s", dist, err, spd, brake ? " braking" : "");
        return false;
    }

    private static boolean steerHeli(Entity v, State st, Vec3 target, double arriveRadius) {
        double dist = horizontalDistance(v, target);
        double targetY = target.y + HELI_HOVER_ABOVE;
        double dy = targetY - v.getY();
        boolean up = dy > 1.5;
        boolean down = dy < -2.5;
        if (dist <= arriveRadius) {
            SwVehicleCompat.setInputs(v, false, false, false, false, up, down, false);
            SwVehicleCompat.mouseInput(v, 0, 0);
            st.lastNote = "hovering at target";
            return Math.abs(dy) < 3;
        }
        double err = headingError(v, target);
        double absErr = Math.abs(err);
        boolean turning = absErr > 6;
        learnTurnSign(st, absErr, turning);
        double yawInput = turning ? Mth.clamp(err * 0.15, -6, 6) * st.turnSign : 0;
        SwVehicleCompat.mouseInput(v, yawInput, 0);
        boolean forward = absErr < 35;
        SwVehicleCompat.setInputs(v, forward, false, false, false, up, down, forward && dist > 40);
        st.lastNote = String.format("heli dist=%.1f err=%.0f dy=%.1f", dist, err, dy);
        return false;
    }
}
