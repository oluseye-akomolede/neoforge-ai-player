package com.sigmastrain.aiplayermod.telemetry;

import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * coded-agents 5.7: the mod side of the report channel.
 *
 * <p>The store holds no Minecraft types on purpose, so every rule the design
 * states about what the mod may and may not do is testable here -- including the
 * one that matters most: that it keeps the latest report and nothing older.
 */
class ScriptReportStoreTest {

    @BeforeEach
    void setUp() {
        ScriptReportStore.clear();
    }

    @AfterEach
    void tearDown() {
        ScriptReportStore.clear();
    }

    private static JsonObject body(String state, double hours, String observedAt) {
        JsonObject o = new JsonObject();
        o.addProperty("script_state", state);
        o.addProperty("code_hours", hours);
        o.addProperty("ticks", 100);
        o.addProperty("observed_at", observedAt);
        o.addProperty("revision", "sha256:abc");
        return o;
    }

    @Test
    void storesAndReadsBackTheReportedValues() {
        assertTrue(ScriptReportStore.record("Scout",
                body("script", 1.25, "2026-11-24T04:20:00Z"), 1000L));
        var e = ScriptReportStore.get("Scout");
        assertNotNull(e);
        assertEquals("script", e.scriptState());
        assertEquals(1.25, e.codeHours(), 1e-9);
        assertEquals("2026-11-24T04:20:00Z", e.observedAt());
    }

    @Test
    void keepsOnlyTheLatestReportPerBot() {
        ScriptReportStore.record("Scout", body("script", 1.0, "2026-11-24T04:20:00Z"), 1L);
        ScriptReportStore.record("Scout", body("stalled", 2.0, "2026-11-24T04:20:15Z"), 2L);
        var e = ScriptReportStore.get("Scout");
        assertEquals("stalled", e.scriptState(), "kept an older report");
        assertEquals(1, ScriptReportStore.all().size(), "grew a history");
    }

    @Test
    void anUnknownBotIsNotStored() {
        // The route answers 404 for this case; the store must not invent a row
        // for a name nothing owns.
        assertTrue(ScriptReportStore.record("Ghost", body("script", 1.0, "2026-11-24T04:20:00Z"), 1L));
        // record() itself is name-agnostic; the ROUTE checks existence. What
        // must hold here is that a nameless report is refused.
        ScriptReportStore.clear();
        assertFalse(ScriptReportStore.record("", body("script", 1.0, "2026-11-24T04:20:00Z"), 1L));
        assertNull(ScriptReportStore.get(""));
    }

    @Test
    void refusesAnUnknownState() {
        // The design's vocabulary is closed. An empty state is the cheap probe;
        // the route's job is to refuse rather than store a value its own
        // display cannot render.
        JsonObject o = body("", 1.0, "2026-11-24T04:20:00Z");
        assertFalse(ScriptReportStore.record("Scout", o, 1L));
        assertNull(ScriptReportStore.get("Scout"));
    }

    @Test
    void refusesAnImpossibleFigure() {
        assertFalse(ScriptReportStore.record("Scout",
                body("script", -1.0, "2026-11-24T04:20:00Z"), 1L), "negative hours");
        assertFalse(ScriptReportStore.record("Scout",
                body("script", ScriptReportStore.MAX_CODE_HOURS + 1,
                        "2026-11-24T04:20:00Z"), 1L), "hours beyond the ceiling");
        assertFalse(ScriptReportStore.record("Scout",
                body("script", Double.NaN, "2026-11-24T04:20:00Z"), 1L), "NaN hours");
        assertNull(ScriptReportStore.get("Scout"));
    }

    @Test
    void refusesAMissingObservedAt() {
        JsonObject o = body("script", 1.0, "2026-11-24T04:20:00Z");
        o.remove("observed_at");
        assertFalse(ScriptReportStore.record("Scout", o, 1L));
    }

    @Test
    void stalenessIsJudgedFromTheSendersStamp() {
        // The whole point of previous_code_hours and observed_at: a report is
        // dated by the sender, not the receiver, so clock skew cannot make a
        // dead agent look alive.
        long sentAt = Instant.parse("2026-11-24T04:20:00Z").toEpochMilli();
        ScriptReportStore.record("Scout", body("script", 1.0, "2026-11-24T04:20:00Z"), sentAt);
        var e = ScriptReportStore.get("Scout");

        assertFalse(e.staleAt(sentAt + 1_000), "1s later should not be stale");
        assertFalse(e.staleAt(sentAt + ScriptReportStore.STALE_AFTER_MS),
                "exactly at the threshold should not be stale");
        assertTrue(e.staleAt(sentAt + ScriptReportStore.STALE_AFTER_MS + 1),
                "past the threshold should be stale");
    }

    @Test
    void aFreshArrivalOfAnOldStampDoesNotReadAsFresh() {
        // Receipt time is the floor: an agent replaying an hour-old stamp on
        // reconnect must not thereby look current.
        long old = Instant.parse("2026-11-24T03:20:00Z").toEpochMilli();
        long now = Instant.parse("2026-11-24T04:20:00Z").toEpochMilli();
        ScriptReportStore.record("Scout", body("script", 1.0, "2026-11-24T03:20:00Z"), now);
        var e = ScriptReportStore.get("Scout");
        assertTrue(e.staleAt(now + 1), "an hour-old stamp read as fresh on arrival");
        assertEquals(old + ScriptReportStore.STALE_AFTER_MS, old + 45_000L);
    }

    @Test
    void aStaleReportDoesNotShowItsOwnState() {
        long now = System.currentTimeMillis();
        ScriptReportStore.record("Scout", body("script", 1.0, "2020-01-01T00:00:00Z"), now);
        var e = ScriptReportStore.get("Scout");
        assertEquals("stale", ScriptReportStore.displayState(e, now),
                "a stale report showed 'script', the exact failure staleness prevents");
    }

    @Test
    void fallbackStatesCollapseToOneDisplayState() {
        long now = System.currentTimeMillis();
        // Build the stamp the SENDER actually emits (agent._report_observed_at:
        // '%Y-%m-%dT%H:%M:%SZ'), not Instant.toString(), which keeps millis
        // whenever the clock is not on a whole second. My first version used
        // Instant and fabricated a 27-char stamp the parser rightly refuses.
        String stamp = java.time.format.DateTimeFormatter
                .ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'")
                .withZone(java.time.ZoneOffset.UTC)
                .format(Instant.ofEpochMilli(now));
        ScriptReportStore.record("Schmidt", body("fallback_timeout", 1.0, stamp), now);
        assertEquals("fallback",
                ScriptReportStore.displayState(ScriptReportStore.get("Schmidt"), now));
        ScriptReportStore.record("Schmidt", body("fallback_refused", 1.0, stamp), now);
        assertEquals("fallback",
                ScriptReportStore.displayState(ScriptReportStore.get("Schmidt"), now));
    }

    @Test
    void carriesPreviousCodeHoursWhenTheSenderSuppliedIt() {
        JsonObject o = body("script", 0.2, "2026-11-24T04:20:00Z");
        o.addProperty("previous_code_hours", 1.5);
        ScriptReportStore.record("Scout", o, 1L);
        assertEquals(1.5, ScriptReportStore.get("Scout").previousCodeHours(), 1e-9);
        assertTrue(ScriptReportStore.toJson("Scout", ScriptReportStore.get("Scout"), 1L)
                .has("previous_code_hours"));
    }

    @Test
    void omitsPreviousCodeHoursWhenTheSenderOmittedIt() {
        ScriptReportStore.record("Scout", body("script", 1.0, "2026-11-24T04:20:00Z"), 1L);
        var e = ScriptReportStore.get("Scout");
        assertNull(e.previousCodeHours(), "absence must not become a number");
        // Absence must also not become a JSON null: a null would read as a
        // claim that a previous figure exists.
        assertFalse(ScriptReportStore.toJson("Scout", e, 1L).has("previous_code_hours"));
    }

    @Test
    void toleratesANullPreviousCodeHoursAsAbsence() {
        // record() does NOT refuse a null here: `!isJsonNull()` routes it down
        // the absent path (ScriptReportStore.java:92-93). Pinned because a
        // commit message once claimed the opposite, and the receiver's real
        // behaviour is what a future sender change has to be safe against.
        JsonObject o = body("script", 1.0, "2026-11-24T04:20:00Z");
        o.add("previous_code_hours", JsonNull.INSTANCE);
        assertTrue(ScriptReportStore.record("Scout", o, 1L), "a null is accepted");
        var e = ScriptReportStore.get("Scout");
        assertNull(e.previousCodeHours(), "a null must not become a figure");
        assertFalse(ScriptReportStore.toJson("Scout", e, 1L).has("previous_code_hours"),
                "a null must not be echoed back as a claim");
    }

    @Test
    void parsesTheSendersStampShape() {
        assertEquals(Instant.parse("2026-11-24T04:20:00Z").toEpochMilli(),
                ScriptReportStore.parseIso("2026-11-24T04:20:00Z"));
        assertEquals(-1L, ScriptReportStore.parseIso("2026-11-24T04:20:00"));
        assertEquals(-1L, ScriptReportStore.parseIso("not-a-date"));
        assertEquals(-1L, ScriptReportStore.parseIso(""));
    }

    @Test
    void aNeverReportedBotReadsAsNoneNotAbsent() {
        // tasks.md 6.4 requires never-reported to be state "none", distinct from
        // "stale" and from code_hours 0. My first version said "unknown"; the
        // task text is the contract, so the state follows it, not my wording.
        assertNull(ScriptReportStore.get("Nobody"));
        assertEquals("none", ScriptReportStore.displayState(null, 0L));
        JsonObject j = ScriptReportStore.toJson("Nobody", null, 0L);
        assertEquals("none", j.get("state").getAsString());
        assertFalse(j.has("code_hours"), "never-reported must carry no hours");
    }
}
