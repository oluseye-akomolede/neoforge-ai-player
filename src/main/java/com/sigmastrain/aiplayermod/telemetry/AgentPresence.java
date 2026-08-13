package com.sigmastrain.aiplayermod.telemetry;

/**
 * Is the agent alive? The mod can't know directly — but the agent polls
 * telemetry constantly (talk every 2 s, escalations while blocked, orders),
 * so "when did an agent-tagged request last arrive" is an honest proxy.
 *
 * <p>Requests are agent-tagged by the {@code X-Agent-Id} header (set in the
 * agent's api.py). Dashboard and player traffic never carry it, so a dead
 * agent can't be masked by a live dashboard.
 */
public final class AgentPresence {

    private AgentPresence() {}

    /** Considered alive when heard from within this window. */
    public static final int ALIVE_WINDOW_SECONDS = 15;

    private static volatile long lastContactMillis = 0;

    public static void touch() {
        lastContactMillis = System.currentTimeMillis();
    }

    /**
     * 0 while the agent is alive (heard within the window); otherwise the
     * real silence in seconds, quantized to 5 so the fleet snapshot only
     * changes (and therefore only resends) every 5 s while down.
     */
    public static int silentSeconds() {
        long last = lastContactMillis;
        if (last == 0) return 999; // never heard from since boot
        long s = (System.currentTimeMillis() - last) / 1000;
        if (s < ALIVE_WINDOW_SECONDS) return 0;
        return (int) Math.min(999, (s / 5) * 5);
    }
}
