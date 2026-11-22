package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.level.Level;
import net.minecraft.world.phys.Vec3;

import java.util.LinkedHashMap;
import java.util.Map;

public class GotoBehavior implements Behavior {
    private final com.sigmastrain.aiplayermod.bot.VehicleDriver.State rideState = new com.sigmastrain.aiplayermod.bot.VehicleDriver.State();
    private BotPlayer lastBot;
    private final ProgressReport progress = new ProgressReport();
    private double targetX, targetY, targetZ;
    private double requestedX, requestedY, requestedZ;
    private boolean targetEnclosed;
    private double arriveDistance = 2.0;
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;
    private int totalTicks;
    private boolean flying;

    // A target buried by up to this many blocks is lifted to the first clear
    // standing spot above and the adjustment is REPORTED. Beyond it the caller
    // meant that exact place, so the GOTO fails rather than relocating: trial
    // 4.2 sent (-123,-44,-152) and the old unbounded search walked the target
    // 36 blocks up to the surface, through a different cave.
    private static final int GOTO_MAX_LIFT = 3;

    private static final int MAX_TICKS = 600;
    private static final double SPRINT_SPEED = 0.4;
    private static final double FLY_SPEED = 0.8;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final double TELEPORT_THRESHOLD = 64.0;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("moving");
        this.requestedX = directive.getX();
        this.requestedY = directive.getY();
        this.requestedZ = directive.getZ();
        this.targetX = this.requestedX;
        this.targetY = this.requestedY;
        this.targetZ = this.requestedZ;
        this.targetEnclosed = false;

        Level level = bot.getPlayer().level();
        LiftDecision lift = decideLift(BlockPos.containing(requestedX, requestedY, requestedZ),
                pos -> {
                    var state = level.getBlockState(pos);
                    return state.isAir() || state.canBeReplaced();
                },
                (int) requestedY);
        if (!lift.reachable()) {
            // No clear standing spot within the bound: this target is enclosed.
            // Fail rather than walk/climb/teleport elsewhere.
            this.targetEnclosed = true;
            progress.setFailureReason(lift.failureReason());
            return;
        }
        this.targetY = lift.targetY();

        if (lift.lifted()) {
            // Report the adjustment so a script's arrival check can be written
            // against what happened, not against what it asked for.
            Map<String, Object> adjusted = new LinkedHashMap<>();
            adjusted.put("x", targetX);
            adjusted.put("y", targetY);
            adjusted.put("z", targetZ);
            Map<String, Object> requested = new LinkedHashMap<>();
            requested.put("x", requestedX);
            requested.put("y", requestedY);
            requested.put("z", requestedZ);
            progress.putResult("adjusted_from", requested);
            progress.putResult("adjusted_to", adjusted);
        }

        if (directive.getExtra().containsKey("distance")) {
            this.arriveDistance = Double.parseDouble(directive.getExtra().get("distance"));
        }
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        this.totalTicks = 0;
        this.flying = false;
    }

    /**
     * The outcome of resolving a GOTO target against the terrain: where the bot
     * should actually go, or why it cannot.
     */
    public record LiftDecision(boolean reachable, double targetY, boolean lifted, String failureReason) {
        static LiftDecision goTo(double y, boolean lifted) {
            return new LiftDecision(true, y, lifted, null);
        }

        static LiftDecision enclosed(int maxLift, double x, double y, double z) {
            return new LiftDecision(false, y, false, String.format(
                    "target_enclosed: no clear standing position within %d blocks above (%.1f, %.1f, %.1f)",
                    maxLift, x, y, z));
        }
    }

    /**
     * Resolve a requested GOTO target to a standing position, lifting at most
     * {@link #GOTO_MAX_LIFT} blocks to find one with clear feet and head.
     *
     * <p>Pure so the bound is testable without a server: {@code clear} answers
     * "can a player stand in this block", and is the only thing the live path
     * supplies. Fails rather than returning a distant position -- an adjusted
     * destination the caller is not told about is trial 4.2.
     */
    public static LiftDecision decideLift(BlockPos requested, java.util.function.Predicate<BlockPos> clear,
                                          int requestedYForMessage) {
        BlockPos cursor = requested;
        for (int lift = 0; lift <= GOTO_MAX_LIFT; lift++) {
            if (clear.test(cursor) && clear.test(cursor.above())) {
                return LiftDecision.goTo(cursor.getY(), lift > 0);
            }
            cursor = cursor.above();
        }
        return LiftDecision.enclosed(GOTO_MAX_LIFT, requested.getX(), requestedYForMessage, requested.getZ());
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (targetEnclosed) {
            // start() found no clear standing spot within the bound. Report it
            // as a failure this tick; never fall through to moving anywhere.
            return BehaviorResult.FAILED;
        }
        ServerPlayer player = bot.getPlayer();
        Vec3 currentPos = player.position();
        Vec3 target = new Vec3(targetX, targetY, targetZ);
        double distance = currentPos.distanceTo(target);

        if (distance <= arriveDistance) {
            progress.logEvent("Arrived at destination");
            // The actual arrival, so a COMPLETED GOTO says where it ended up
            // (which differs from the request when the target was lifted).
            // An {x,y,z} map, like state.position -- not a "x, y, z" string,
            // which is the shape bug that let trial 4.3 go unnoticed.
            progress.putResult("arrived_at", Map.of(
                    "x", Math.round(currentPos.x * 10.0) / 10.0,
                    "y", Math.round(currentPos.y * 10.0) / 10.0,
                    "z", Math.round(currentPos.z * 10.0) / 10.0));
            return BehaviorResult.SUCCESS;
        }

        if (++totalTicks > MAX_TICKS) {
            progress.setFailureReason("Timed out after " + MAX_TICKS + " ticks");
            return BehaviorResult.FAILED;
        }

        // Aboard a vehicle: drive there instead of walking/teleporting.
        lastBot = bot;
        if (com.sigmastrain.aiplayermod.brain.VehicleRide.steer(bot, player, rideState, target, arriveDistance)) {
            progress.setPhase("driving (aboard)");
            return BehaviorResult.RUNNING;
        }

        if (distance > TELEPORT_THRESHOLD) {
            Vec3 dir = target.subtract(currentPos).normalize();
            player.moveTo(targetX - dir.x * arriveDistance, targetY, targetZ - dir.z * arriveDistance);
            flying = false;
            yVelocity = 0;
            return BehaviorResult.RUNNING;
        }

        double heightDiff = Math.abs(targetY - currentPos.y);

        if (heightDiff > 4.0) {
            flying = true;
        }

        if (flying) {
            Vec3 dir = target.subtract(currentPos).normalize();
            double moveSpeed = Math.min(FLY_SPEED, distance - arriveDistance + 0.5);
            if (moveSpeed < 0.1) moveSpeed = 0.1;
            player.moveTo(
                    currentPos.x + dir.x * moveSpeed,
                    currentPos.y + dir.y * moveSpeed,
                    currentPos.z + dir.z * moveSpeed
            );
            bot.lookAt(targetX, targetY, targetZ);
            return BehaviorResult.RUNNING;
        }

        Vec3 direction = target.subtract(currentPos).normalize();

        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, direction)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }

        if (lastPos != null && currentPos.distanceTo(lastPos) < 0.01) {
            ticksStuck++;
            if (ticksStuck > 20) {
                flying = true;
                ticksStuck = 0;
                return BehaviorResult.RUNNING;
            }
        } else {
            ticksStuck = 0;
        }
        lastPos = currentPos;

        player.move(MoverType.SELF, new Vec3(direction.x * SPRINT_SPEED, yVelocity, direction.z * SPRINT_SPEED));
        bot.lookAt(targetX, targetY, targetZ);
        return BehaviorResult.RUNNING;
    }

    @Override
    public String describeState() {
        return String.format("Moving to %.0f, %.0f, %.0f", targetX, targetY, targetZ);
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {
        if (lastBot != null && lastBot.getPlayer() != null) com.sigmastrain.aiplayermod.brain.VehicleRide.release(lastBot.getPlayer());
    }
}
