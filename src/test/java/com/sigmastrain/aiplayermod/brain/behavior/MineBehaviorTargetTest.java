package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.DirectiveType;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * A MINE with no block id must fail here, not in tick().
 *
 * <p>The bug this pins, from the live trial on 2026-11-22: a script sent
 * `MINE {x, y, z}` with no target. MineBehavior.start() stored the null and
 * returned; the phase was never set; the first tick() hit
 * targetBlock.toLowerCase() and threw. The behaviour stayed installed, so
 * every server tick threw again -- the server thread fell behind and the bot
 * stopped answering. Rejecting at start() is the mod's own guard, independent
 * of whether the agent's binding catches it first.
 */
class MineBehaviorTargetTest {

    private static Directive mine(String target) {
        return Directive.builder(DirectiveType.MINE).target(target).count(1).build();
    }

    @Test
    void a_mine_with_no_target_is_rejected_before_any_state_is_kept() {
        MineBehavior behavior = new MineBehavior();
        // bot is null on purpose: the guard must fire before the behaviour
        // touches the world, so a null bot never gets dereferenced.
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> behavior.start(null, mine(null)));
        assertTrue(e.getMessage().contains("block id"),
                "the refusal must say what to send, got: " + e.getMessage());
    }

    /** "   " passes a presence check and reaches the same toLowerCase() path. */
    @Test
    void a_blank_target_is_rejected_too() {
        for (String blank : new String[]{"", "   ", "\t"}) {
            assertThrows(IllegalArgumentException.class,
                    () -> new MineBehavior().start(null, mine(blank)),
                    "target=" + blank);
        }
    }

    /** The rejection is not a blanket refusal: a real block id still starts. */
    @Test
    void a_real_target_gets_past_the_guard_and_on_to_the_bot() {
        // No server here, so start() fails later on the null bot -- but it must
        // fail with a NullPointerException from beyond the guard, not with the
        // target rejection. Distinguishing the two is the point.
        MineBehavior behavior = new MineBehavior();
        NullPointerException npe = assertThrows(NullPointerException.class,
                () -> behavior.start(null, mine("minecraft:iron_ore")));
        assertTrue(npe.getMessage() == null || !npe.getMessage().contains("block id"),
                "a valid target was refused by the guard: " + npe.getMessage());
    }
}
