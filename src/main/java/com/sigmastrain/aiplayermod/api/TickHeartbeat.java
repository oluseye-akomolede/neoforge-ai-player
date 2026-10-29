package com.sigmastrain.aiplayermod.api;

import java.util.function.Consumer;
import java.util.function.LongSupplier;

/**
 * Heartbeat for {@code GET /health}: the time of the last completed server tick.
 *
 * <p>The HTTP handler reads this object and never touches the server thread. A
 * handler that hopped to the server thread ({@code server.execute}) would queue
 * behind the very stall it exists to detect and would time out instead of
 * answering, which the kubelet scores as an API failure rather than a tick
 * failure. Everything here is lock-free and answers in constant time.
 *
 * <p>Times are taken from a monotonic clock ({@link System#nanoTime()}), never
 * from wall-clock time: an NTP step would fabricate a stall in one direction and
 * hide a real one in the other.
 */
public final class TickHeartbeat {

    /** The startupProbe's own budget: 60 x 15 s. Bounds the "starting" state. */
    public static final int STARTUP_BUDGET_SECONDS = 900;

    /** Default stall threshold in seconds. */
    public static final int DEFAULT_STALL_SECONDS = 120;

    private static final long NANOS_PER_SECOND = 1_000_000_000L;

    private final LongSupplier nanoClock;
    private final int thresholdSeconds;
    private final long listeningSinceNanos;

    /** 0 means no tick has completed yet. Written by the server thread only. */
    private volatile long lastTickNanos;

    public TickHeartbeat(int thresholdSeconds, LongSupplier nanoClock) {
        this.thresholdSeconds = thresholdSeconds;
        this.nanoClock = nanoClock;
        this.listeningSinceNanos = nanoClock.getAsLong();
    }

    /**
     * Stamps a completed tick. Called at the END of the server tick, so a tick
     * that throws on its way through does not refresh the heartbeat.
     */
    public void recordTick() {
        lastTickNanos = nanoClock.getAsLong();
    }

    public int thresholdSeconds() {
        return thresholdSeconds;
    }

    /** Probes on the real clock. The handler's path. */
    public Probe probe() {
        return probe(nanoClock.getAsLong());
    }

    /** Probes at an explicit monotonic instant. Pure: no clock read, no blocking. */
    public Probe probe(long nowNanos) {
        long last = lastTickNanos;
        if (last != 0L) {
            long ageSeconds = Math.max(0L, nowNanos - last) / NANOS_PER_SECOND;
            if (ageSeconds > thresholdSeconds) {
                return new Probe(503, "stalled",
                        "tick age " + ageSeconds + " s exceeds threshold " + thresholdSeconds + " s",
                        ageSeconds);
            }
            return new Probe(200, "ok", null, ageSeconds);
        }
        // No tick yet: the API server starts at ServerStartedEvent, which
        // precedes the first tick, and the startup probe has to keep passing.
        // The state is bounded by that probe's own budget so a hang before the
        // first tick cannot answer 200 forever.
        long sinceListening = Math.max(0L, nowNanos - listeningSinceNanos);
        if (sinceListening >= STARTUP_BUDGET_SECONDS * NANOS_PER_SECOND) {
            return new Probe(503, "stalled", "never ticked", null);
        }
        return new Probe(200, "starting", null, null);
    }

    /**
     * The threshold: system property, else environment variable, else the
     * default. An unparseable or non-positive value falls back and produces
     * exactly one warning through {@code warn}.
     */
    public static int resolveThresholdSeconds(String propertyValue, String envValue,
                                              int fallback, Consumer<String> warn) {
        String raw = propertyValue != null ? propertyValue : envValue;
        if (raw == null || raw.isBlank()) {
            return fallback;
        }
        try {
            int parsed = Integer.parseInt(raw.trim());
            if (parsed > 0) {
                return parsed;
            }
            warn.accept("Ignoring non-positive health stall threshold '" + raw
                    + "'; using " + fallback + " s");
        } catch (NumberFormatException e) {
            warn.accept("Ignoring unparseable health stall threshold '" + raw
                    + "'; using " + fallback + " s");
        }
        return fallback;
    }

    /**
     * The probe port: system property, else environment variable, else the
     * fallback. A blank value is not a misconfiguration and falls through
     * silently. A non-numeric value, a value outside 1-65535, or a value equal
     * to {@code resolvedApiPort} is rejected with exactly one warning.
     *
     * <p>The collision check compares against {@code resolvedApiPort}—itself
     * configurable—rather than against the constant 3100, because the API port
     * may have been moved by the same property/env mechanism. The collision is
     * caught here rather than left to the bind because a bind failure cannot
     * distinguish it from another process holding the port; only an early check
     * makes the fallback reachable at all. Falling back rather than failing is
     * deliberate: a probe listener that does not bind leaves /health unanswered,
     * which is the failure the dedicated listener exists to prevent.
     */
    public static int resolveProbePort(String propertyValue, String envValue,
                                       int resolvedApiPort, int fallback, Consumer<String> warn) {
        String raw = propertyValue != null ? propertyValue : envValue;
        if (raw == null || raw.isBlank()) {
            return fallback;
        }
        try {
            int parsed = Integer.parseInt(raw.trim());
            if (parsed < 1 || parsed > 65535) {
                warn.accept("Ignoring out-of-range probe port '" + raw
                        + "'; using " + fallback);
                return fallback;
            }
            if (parsed == resolvedApiPort) {
                warn.accept("Ignoring probe port '" + raw
                        + "' (collides with API port); using " + fallback);
                return fallback;
            }
            return parsed;
        } catch (NumberFormatException e) {
            warn.accept("Ignoring unparseable probe port '" + raw
                    + "'; using " + fallback);
            return fallback;
        }
    }

    /** One answer for {@code GET /health}. {@code ageSeconds} is null until a tick lands. */
    public record Probe(int httpStatus, String status, String reason, Long ageSeconds) {
    }
}
