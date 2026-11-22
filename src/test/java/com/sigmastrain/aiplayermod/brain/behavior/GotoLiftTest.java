package com.sigmastrain.aiplayermod.brain.behavior;

import net.minecraft.core.BlockPos;
import org.junit.jupiter.api.Test;

import java.util.HashSet;
import java.util.Set;
import java.util.function.Predicate;

import static org.junit.jupiter.api.Assertions.*;

/**
 * The bounded GOTO lift, tested without a server.
 *
 * <p>trial 4.2 (2026-11-22): a script sent {@code GOTO (-123, -44, -152)} at an
 * enclosed {@code deepslate_diamond_ore}. The old search raised targetY until
 * feet and head were clear, stopping only at the build limit, so the bot was
 * sent to {@code y = -8} -- 36 blocks up, into a different cave -- and the
 * directive COMPLETED with no indication the destination had moved.
 *
 * <p>{@link GotoBehavior#decideLift} is pure so that bound is checkable here.
 * It does NOT cover movement, teleporting or arrival reporting; those need a
 * live Level and are covered by a trial.
 */
class GotoLiftTest {

    /** Clear only the given positions -- the terrain, as a set. */
    private static Predicate<BlockPos> clearOnly(Set<BlockPos> open) {
        return open::contains;
    }

    /** Nothing is clear: solid rock all the way up. */
    private static Predicate<BlockPos> solidRock() {
        return pos -> false;
    }

    @Test
    void trial_4_2s_enclosed_target_is_unreachable_not_lifted_36_blocks() {
        // (-123,-44,-152) surrounded by stone, exactly trial 4.2's case.
        BlockPos requested = new BlockPos(-123, -44, -152);

        GotoBehavior.LiftDecision d = GotoBehavior.decideLift(requested, solidRock(), -44);

        assertFalse(d.reachable(),
                "an enclosed target must be reported unreachable, not relocated");
        assertTrue(d.failureReason().startsWith("target_enclosed"),
                "the reason must be target_enclosed, got: " + d.failureReason());
        assertTrue(d.failureReason().contains("-123")
                        && d.failureReason().contains("-44")
                        && d.failureReason().contains("-152"),
                "the failure must name the coordinates asked for, got: " + d.failureReason());
    }

    @Test
    void an_open_target_is_not_lifted() {
        BlockPos requested = new BlockPos(10, 64, 10);
        Set<BlockPos> open = Set.of(requested, requested.above());

        GotoBehavior.LiftDecision d = GotoBehavior.decideLift(requested, clearOnly(open), 64);

        assertTrue(d.reachable());
        assertFalse(d.lifted(), "a standable target needs no adjustment");
        assertEquals(64, d.targetY());
    }

    @Test
    void a_target_under_a_shallow_ledge_is_lifted_and_flagged() {
        // Feet buried one block; the block above that is clear.
        BlockPos requested = new BlockPos(5, 70, 5);
        BlockPos standing = requested.above();
        Set<BlockPos> open = Set.of(standing, standing.above());

        GotoBehavior.LiftDecision d = GotoBehavior.decideLift(requested, clearOnly(open), 70);

        assertTrue(d.reachable(), "one buried block is within the bound");
        assertTrue(d.lifted(), "the caller must be told the destination moved");
        assertEquals(71, d.targetY());
    }

    @Test
    void a_target_buried_exactly_the_bound_is_lifted() {
        BlockPos requested = new BlockPos(0, 20, 0);
        BlockPos standing = requested.above(3);
        Set<BlockPos> open = Set.of(standing, standing.above());

        GotoBehavior.LiftDecision d = GotoBehavior.decideLift(requested, clearOnly(open), 20);

        assertTrue(d.reachable(), "exactly GOTO_MAX_LIFT blocks up is still reachable");
        assertTrue(d.lifted());
        assertEquals(23, d.targetY());
    }

    @Test
    void a_target_buried_one_past_the_bound_is_unreachable() {
        BlockPos requested = new BlockPos(0, 20, 0);
        BlockPos standing = requested.above(4);
        Set<BlockPos> open = Set.of(standing, standing.above());

        GotoBehavior.LiftDecision d = GotoBehavior.decideLift(requested, clearOnly(open), 20);

        assertFalse(d.reachable(),
                "one block past GOTO_MAX_LIFT is a different destination, not an adjustment");
        assertTrue(d.failureReason().startsWith("target_enclosed"));
    }

    @Test
    void a_timed_out_goto_names_the_destination_it_was_walking_to() {
        // Review note (a) on 465b61e: the timeout reason said only the tick
        // count, while describeState() kept reporting the LIFTED target -- so
        // for a lifted GOTO the only destination the caller ever saw was one
        // they did not ask for. The reason must name where it was going.
        String reason = GotoBehavior.timeoutReason(600, 10.0, 65.0, -3.0);

        assertTrue(reason.contains("600"), reason);
        assertTrue(reason.contains("10.0") && reason.contains("65.0")
                        && reason.contains("-3.0"),
                "the timeout must name the destination, got: " + reason);
    }

    @Test
    void the_lift_is_bounded_so_it_never_searches_to_the_surface() {
        // A vertical shaft, clear only far above. The old code climbed to it.
        BlockPos requested = new BlockPos(7, -60, 7);
        BlockPos highUp = requested.above(36);
        Set<BlockPos> open = Set.of(highUp, highUp.above());

        GotoBehavior.LiftDecision d = GotoBehavior.decideLift(requested, clearOnly(open), -60);

        assertFalse(d.reachable(),
                "a clear spot 36 blocks up must NOT be taken -- that is trial 4.2");
        assertTrue(d.failureReason().contains("target_enclosed"));
    }
}
