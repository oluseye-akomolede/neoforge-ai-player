package com.sigmastrain.aiplayermod.api;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Unit tests for the /health tick heartbeat: the four states of the endpoint,
 * the threshold rules, and the property that the answer never waits on the
 * server thread.
 */
class TickHeartbeatTest {

    private static final long S = 1_000_000_000L; // one second in nanos

    /** A heartbeat whose clock the test controls. */
    private static final class Clock {
        final AtomicLong now = new AtomicLong(1_000_000_000_000L);
        final TickHeartbeat heartbeat = new TickHeartbeat(120, now::get);

        void advanceSeconds(long seconds) {
            now.addAndGet(seconds * S);
        }
    }

    @Test
    void freshTickInTimeIsOk() {
        Clock c = new Clock();
        c.heartbeat.recordTick();
        c.advanceSeconds(5);

        TickHeartbeat.Probe p = c.heartbeat.probe();

        assertEquals(200, p.httpStatus());
        assertEquals("ok", p.status());
        assertNull(p.reason());
        assertEquals(5L, p.ageSeconds());
    }

    @Test
    void ageBeyondThresholdIsStalled() {
        Clock c = new Clock();
        c.heartbeat.recordTick();
        c.advanceSeconds(121);

        TickHeartbeat.Probe p = c.heartbeat.probe();

        assertEquals(503, p.httpStatus());
        assertEquals("stalled", p.status());
        assertEquals(121L, p.ageSeconds());
        assertTrue(p.reason().contains("121"), "reason names the age: " + p.reason());
        assertTrue(p.reason().contains("120"), "reason names the threshold: " + p.reason());
    }

    @Test
    void ageExactlyAtThresholdIsStillOk() {
        Clock c = new Clock();
        c.heartbeat.recordTick();
        c.advanceSeconds(120);

        assertEquals(200, c.heartbeat.probe().httpStatus());
    }

    @Test
    void neverTickedInsideTheStartupBudgetIsStarting() {
        Clock c = new Clock();
        c.advanceSeconds(TickHeartbeat.STARTUP_BUDGET_SECONDS - 1);

        TickHeartbeat.Probe p = c.heartbeat.probe();

        assertEquals(200, p.httpStatus());
        assertEquals("starting", p.status());
        assertNull(p.ageSeconds());
        assertNull(p.reason());
    }

    @Test
    void neverTickedPastTheStartupBudgetFails() {
        Clock c = new Clock();
        c.advanceSeconds(TickHeartbeat.STARTUP_BUDGET_SECONDS);

        TickHeartbeat.Probe p = c.heartbeat.probe();

        assertEquals(503, p.httpStatus());
        assertEquals("stalled", p.status());
        assertEquals("never ticked", p.reason());
        assertNull(p.ageSeconds());
    }

    @Test
    void aBackwardsClockStepNeitherGoesNegativeNorFabricatesAStall() {
        Clock c = new Clock();
        c.heartbeat.recordTick();
        c.advanceSeconds(-600); // what a wall-clock step would look like

        TickHeartbeat.Probe p = c.heartbeat.probe();

        assertEquals(200, p.httpStatus());
        assertEquals(0L, p.ageSeconds());
    }

    @Test
    void aTickThatLandsClearsTheNeverTickedState() {
        Clock c = new Clock();
        c.advanceSeconds(TickHeartbeat.STARTUP_BUDGET_SECONDS); // would be "never ticked"
        c.heartbeat.recordTick();

        assertEquals(200, c.heartbeat.probe().httpStatus());
        assertEquals("ok", c.heartbeat.probe().status());
    }

    // ── threshold resolution ──

    private static int resolve(String property, String env, List<String> warnings) {
        return TickHeartbeat.resolveThresholdSeconds(property, env,
                TickHeartbeat.DEFAULT_STALL_SECONDS, warnings::add);
    }

    @Test
    void thresholdDefaultsTo120() {
        List<String> warnings = new ArrayList<>();
        assertEquals(120, resolve(null, null, warnings));
        assertEquals(120, resolve("  ", "", warnings));
        assertTrue(warnings.isEmpty(), "no warnings for an absent value");
    }

    @Test
    void thresholdComesFromPropertyOrDefaultEnvWithPropertyWinning() {
        List<String> warnings = new ArrayList<>();
        assertEquals(45, resolve("45", null, warnings));
        assertEquals(45, resolve(null, "45", warnings));
        assertEquals(60, resolve("60", "45", warnings));
        assertTrue(warnings.isEmpty());
    }

    @Test
    void invalidThresholdsFallBackWithExactlyOneWarning() {
        for (String bad : List.of("0", "-3", "abc", "1.5")) {
            List<String> warnings = new ArrayList<>();
            assertEquals(120, resolve(bad, null, warnings), "value " + bad);
            assertEquals(1, warnings.size(), "exactly one WARN for " + bad);
            assertTrue(warnings.get(0).contains(bad), "the warning names the value: " + warnings.get(0));
        }
    }

    // ── the response body and the no-hop property ──

    @Test
    void healthBodyKeepsTheOldFieldsAndAddsTheAge() {
        Map<String, Object> ok = HttpApiServer.healthBody(
                new TickHeartbeat.Probe(200, "ok", null, 7L), "aiplayermod", 3);

        assertEquals("ok", ok.get("status"));
        assertEquals("aiplayermod", ok.get("mod"));
        assertEquals(3, ok.get("bots"));
        assertEquals(7L, ok.get("tick_age_seconds"));
        assertFalse(ok.containsKey("reason"), "no reason on a healthy answer");
    }

    @Test
    void theStartingBodyKeepsAnExplicitNullAgeOnTheWire() {
        Map<String, Object> starting = HttpApiServer.healthBody(
                new TickHeartbeat.Probe(200, "starting", null, null), "aiplayermod", 0);

        // The map holding JsonNull proves nothing: only the serialised bytes reach
        // the client. Use the writer /health actually uses.
        String wire = HttpApiServer.HEALTH_GSON.toJson(starting);
        JsonObject parsed = JsonParser.parseString(wire).getAsJsonObject();

        assertTrue(parsed.has("tick_age_seconds"), "the wire body keeps the key: " + wire);
        assertTrue(parsed.get("tick_age_seconds").isJsonNull(), "and it is a JSON null: " + wire);
        assertEquals("starting", parsed.get("status").getAsString());
        assertEquals(0, parsed.get("bots").getAsInt());
    }

    @Test
    void theSharedWriterWouldDropTheNullWhichIsWhyHealthHasItsOwn() {
        // Pins the trap this endpoint hit: with the shared config the field name is
        // dropped entirely, not sent as null. If Gson ever changes this, the
        // dedicated HEALTH_GSON above is no longer needed - and this test says so.
        Map<String, Object> starting = HttpApiServer.healthBody(
                new TickHeartbeat.Probe(200, "starting", null, null), "aiplayermod", 0);

        String sharedWire = new GsonBuilder().setPrettyPrinting().create().toJson(starting);

        assertFalse(sharedWire.contains("tick_age_seconds"),
                "the shared writer still drops a null field: " + sharedWire);
    }

    @Test
    void healthBodyCarriesTheReasonOnAFailure() {
        TickHeartbeat.Probe stalled = new TickHeartbeat.Probe(503, "stalled",
                "tick age 130 s exceeds threshold 120 s", 130L);

        Map<String, Object> body = HttpApiServer.healthBody(stalled, "aiplayermod", 0);

        assertEquals("stalled", body.get("status"));
        assertEquals("tick age 130 s exceeds threshold 120 s", body.get("reason"));
    }

    @Test
    void theStalledAnswerIsComputedWithoutWaitingOnAnything() {
        // A server thread stalled for an hour must still produce an answer
        // immediately: probe() reads one volatile field and does arithmetic, and
        // is a pure function of the instant it is given.
        Clock c = new Clock();
        c.heartbeat.recordTick();
        long stalledNow = c.now.get() + 3_600 * S;

        long t0 = System.nanoTime();
        TickHeartbeat.Probe first = c.heartbeat.probe(stalledNow);
        TickHeartbeat.Probe second = c.heartbeat.probe(stalledNow);
        long elapsedMillis = (System.nanoTime() - t0) / 1_000_000L;

        assertEquals(503, first.httpStatus());
        assertEquals(first, second);
        assertTrue(elapsedMillis < 100, "two probes took " + elapsedMillis + " ms");
    }

    @Test
    void theHealthPathCannotReachTheServerThreadEvenIfSomebodyTries() {
        // Permanent guard, so the no-hop property outlives the temporary stall
        // hook: nothing the health answer depends on is allowed to hold a server
        // or an executor handed in from outside. Partial by construction: it sees
        // signatures, not bodies, so a static server accessor inside a method would
        // pass it. The wire-level test above covers the other half.
        for (var ctor : HttpApiServer.class.getDeclaredConstructors()) {
            for (var param : ctor.getParameterTypes()) {
                assertFalse(isServerOrExecutor(param),
                        "constructor parameter " + param.getName() + " can reach the server thread");
            }
        }
        for (var field : HttpApiServer.class.getDeclaredFields()) {
            assertFalse(isServerOrExecutor(field.getType()),
                    "field " + field.getName() + " can reach the server thread");
        }
        assertTrue(java.lang.reflect.Modifier.isStatic(method(HttpApiServer.class, "healthBody").getModifiers()),
                "healthBody must be a static function of its arguments");
        for (var m : TickHeartbeat.class.getDeclaredMethods()) {
            if (m.getName().equals("probe")) {
                for (var param : m.getParameterTypes()) {
                    assertFalse(isServerOrExecutor(param),
                            "probe parameter " + param.getName() + " can reach the server thread");
                }
            }
        }
    }

    private static boolean isServerOrExecutor(Class<?> type) {
        return type.getName().equals("net.minecraft.server.MinecraftServer")
                || java.util.concurrent.Executor.class.isAssignableFrom(type);
    }

    private static java.lang.reflect.Method method(Class<?> owner, String name) {
        for (var m : owner.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError(owner.getSimpleName() + "." + name + " is gone");
    }
}
