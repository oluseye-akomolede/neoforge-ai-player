package com.sigmastrain.aiplayermod.bot;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The day time the status reports, and whether it is night.
 *
 * <p>The prod failure this pins (2026-11-22): Mystic announced "it's getting
 * dark — overworld time is 0 (night)" in daylight, because the snapshot had no
 * time and the script invented a clock that reached 0 after 600 ticks. Two
 * things have to be true for that to be impossible: the reading has to be the
 * level's real time, and 0 has to be sunrise rather than night. The second is
 * the one a plausible implementation gets wrong — {@code 0} is a small number,
 * and "small" reads like "dark" if you never check which end of the cycle it
 * is at.
 *
 * <p>The window is vanilla's: monsters spawn from 13000 to 23000, which is the
 * dusk-to-dawn span. Testing the bounds rather than only the middle matters,
 * because an off-by-one at either edge is a script that says "not yet" one tick
 * too long or fires while the sun is still up.
 */
class WorldTimeTest {

    @Test
    void dayTimeIsReducedModulo24000() {
        assertEquals(0, BotPlayer.dayTimeOf(0));
        assertEquals(15000, BotPlayer.dayTimeOf(15000));
        assertEquals(23999, BotPlayer.dayTimeOf(23999));
        // A level that has run for several days keeps counting: 24000 is a new
        // day, not an out-of-range time, and a status reader must never see one.
        assertEquals(0, BotPlayer.dayTimeOf(24000));
        assertEquals(500, BotPlayer.dayTimeOf(24000L + 500));
        assertEquals(500, BotPlayer.dayTimeOf(24000L * 7 + 500));
    }

    @Test
    void dayTimeIsNeverNegativeOrOutOfRange() {
        for (long t = 0; t < 24000L * 3; t += 137) {
            int d = BotPlayer.dayTimeOf(t);
            assertTrue(d >= 0 && d < 24000, "day time " + d + " out of range at " + t);
        }
    }

    @Test
    void sunriseIsNotNight() {
        // The exact value the prod script called night.
        assertFalse(BotPlayer.isNightOf(0), "0 is sunrise, not night");
        assertFalse(BotPlayer.isNightOf(1));
        assertFalse(BotPlayer.isNightOf(1000), "the script counted 0..1000 as night");
    }

    @Test
    void daylightIsNotNight() {
        assertFalse(BotPlayer.isNightOf(6000), "noon");
        assertFalse(BotPlayer.isNightOf(12000));
        assertFalse(BotPlayer.isNightOf(12999), "one tick before dusk");
    }

    @Test
    void duskToDawnIsNight() {
        assertTrue(BotPlayer.isNightOf(13000), "dusk: monsters start spawning");
        assertTrue(BotPlayer.isNightOf(15000));
        assertTrue(BotPlayer.isNightOf(18000), "midnight");
        assertTrue(BotPlayer.isNightOf(22999), "one tick before dawn");
    }

    @Test
    void dawnIsNotNight() {
        assertFalse(BotPlayer.isNightOf(23000), "dawn: monsters stop spawning");
        assertFalse(BotPlayer.isNightOf(23999), "just before sunrise");
    }

    @Test
    void exactlyOneNightWindowPerDayCycle() {
        // The regression shape: a script that decides "is it night" wrongly
        // tends to produce two windows (0..1000 and the real one) or none.
        int windows = 0;
        boolean prev = BotPlayer.isNightOf(23999);
        for (int t = 0; t < 24000; t++) {
            boolean now = BotPlayer.isNightOf(t);
            if (now && !prev) windows++;
            prev = now;
        }
        if (prev) windows++; // wrapped across the cycle boundary
        assertEquals(1, windows, "a day cycle has exactly one night");
    }

    @Test
    void theNightWindowIsTheLengthVanillaUses() {
        int nightTicks = 0;
        for (int t = 0; t < 24000; t++) {
            if (BotPlayer.isNightOf(t)) nightTicks++;
        }
        assertEquals(10000, nightTicks, "13000..22999 inclusive is 10000 ticks");
    }
}
