package com.sigmastrain.aiplayermod.telemetry;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Per-bot ring buffer of thought events pushed by the agent.
 *
 * <p>This is the reverse channel v7 needs: the mod knows only L1, while
 * plans, criteria and verdicts live in the Python agent — which until now
 * only *polled* the mod. The agent pushes its transitions here; the overlay's
 * Mind tab reads them. The reason strings already exist (they have been going
 * to kubectl logs all project); this makes them a game surface.
 *
 * <p>Thread model: written from the HTTP executor, read from the server
 * thread. Each bot's deque is guarded by its own monitor.
 */
public final class TelemetryStore {

    private TelemetryStore() {}

    /** One thought. {@code type} is an open vocabulary — see the agent side. */
    public record ThoughtEvent(long atMillis, String type, String text) {}

    private static final int MAX_EVENTS_PER_BOT = 100;
    private static final Map<String, Deque<ThoughtEvent>> EVENTS = new ConcurrentHashMap<>();

    /** Bots whose stream changed since the last overlay forward. */
    private static final Map<String, Long> DIRTY = new ConcurrentHashMap<>();

    public static void push(String bot, String type, String text) {
        Deque<ThoughtEvent> q = EVENTS.computeIfAbsent(bot, k -> new ArrayDeque<>());
        synchronized (q) {
            q.addLast(new ThoughtEvent(System.currentTimeMillis(), type, text));
            while (q.size() > MAX_EVENTS_PER_BOT) q.removeFirst();
        }
        DIRTY.put(bot, System.currentTimeMillis());
    }

    /** Most recent {@code limit} events, oldest first. */
    public static List<ThoughtEvent> recent(String bot, int limit) {
        Deque<ThoughtEvent> q = EVENTS.get(bot);
        if (q == null) return List.of();
        synchronized (q) {
            List<ThoughtEvent> all = new ArrayList<>(q);
            return all.size() <= limit ? all : all.subList(all.size() - limit, all.size());
        }
    }

    /** Drain-and-clear the set of bots with new events since last call. */
    public static List<String> drainDirty() {
        if (DIRTY.isEmpty()) return List.of();
        List<String> bots = new ArrayList<>(DIRTY.keySet());
        for (String b : bots) DIRTY.remove(b);
        return bots;
    }

    public static void clear(String bot) {
        EVENTS.remove(bot);
        DIRTY.remove(bot);
    }
}
