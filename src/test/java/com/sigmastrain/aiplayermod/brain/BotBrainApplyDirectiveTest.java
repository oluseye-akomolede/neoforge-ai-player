package com.sigmastrain.aiplayermod.brain;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;

/**
 * A directive whose behavior throws in start() fails once, and the brain goes
 * idle instead of keeping the throwing behavior installed.
 *
 * <p>The wedge this pins, from the live trial on 2026-11-22: applyDirective
 * assigned `activeBehavior` BEFORE calling start(), so a MineBehavior with a
 * null target threw in start() and was left installed with no phase. Every
 * server tick then called tick(), which threw again -- the server thread fell
 * behind and the bot stopped answering.
 *
 * <p>Driven through applyDirective(), not tick(): tick() goes on to
 * self-preservation and chat, which need a live ServerPlayer that cannot be
 * built without a running server. applyDirective is where the defect lived and
 * where the fix is, and the bot is null to prove that path needs no entity.
 */
class BotBrainApplyDirectiveTest {

    /** The one directive type whose start() throws before it touches a world. */
    private static Directive mineWithoutTarget() {
        return Directive.builder(DirectiveType.MINE).target(null).count(1).build();
    }

    /** KILLS: assigning the throwing behavior before start() (the shipped bug). */
    @Test
    void a_throwing_start_fails_the_directive_and_does_not_leave_it_active() {
        BotBrain brain = new BotBrain(null);
        Directive d = mineWithoutTarget();

        assertDoesNotThrow(() -> brain.applyDirective(d),
                "a bad directive must not throw out of the brain, or the server thread dies with it");

        assertEquals(DirectiveStatus.FAILED, d.getStatus());
        assertNotNull(d.getFailureReason(), "the directive must carry why it failed");
        assertFalse(brain.hasActiveDirective(),
                "the failed directive must not stay active");
        assertEquals("Standing by", brain.stateLine(),
                "the bot must be back on the idle behavior, not the throwing one");
    }

    /** The failed directive is RETAINED, so the agent's next poll sees the reason. */
    @Test
    void the_failure_is_visible_to_the_next_poll() {
        BotBrain brain = new BotBrain(null);
        Directive d = mineWithoutTarget();
        brain.applyDirective(d);

        assertSame(d, brain.peekDirective());
        assertNotNull(brain.toMap().get("directive"),
                "toMap() must still report the failed directive");
    }

    // NOT ATTEMPTED HERE: that cancelDirective WIPES the retained directive.
    // It does (BotBrain.java:62-64), and that is the mechanism behind trial
    // 4.2 retry -- the agent cancelled a completion it had just read, erasing
    // the record the script polls. But cancelDirective's first statement logs
    // through bot.getPlayer() (BotBrain.java:52-55), so with the null bot this
    // test can build it throws NPE before reaching the clear. Pinning it needs
    // a live ServerPlayer, so it belongs to a game-test or the live trial. The
    // AGENT half -- that no cancel is sent after a completion is read -- is
    // covered server-free by agent/test_poll_directive_retention.py.

    // NOT TESTED HERE: that a later good directive still applies. The success
    // path of applyDirective logs through bot.getPlayer() (BotBrain.java:208),
    // which needs a live ServerPlayer, so it cannot be reached with a null bot
    // -- and BotPlayer's constructor is private and takes one. A server-free
    // test cannot cover recovery; it needs a game-test or a live trial.

    /**
     * A blank target takes the same path as a null one.
     *
     * <p>Does NOT kill the MineBehavior guard -- MineBehavior's own
     * start()/requireTarget() is what rejects this, and removing that guard reds
     * MineBehaviorTargetTest, not this. This pins that the brain's recovery also
     * covers a blank, not only a null.
     */
    @Test
    void a_blank_target_is_refused_too() {
        BotBrain brain = new BotBrain(null);
        Directive d = Directive.builder(DirectiveType.MINE).target("   ").count(1).build();

        assertDoesNotThrow(() -> brain.applyDirective(d));
        assertEquals(DirectiveStatus.FAILED, d.getStatus());
    }
}
