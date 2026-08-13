package com.sigmastrain.aiplayermod.telemetry;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * The L4 inbox — pending questions from the network to the player.
 *
 * <p>The agent detects conditions it should not resolve alone (ambiguous
 * item ids, exhausted retries, an explicit ASK_PLAYER from L3), posts them
 * here, and BLOCKS its plan until the player answers or the wait times out.
 * The overlay renders pending items; responses are stored for the agent to
 * poll. The player is a layer in the pyramid now — this is the seam where
 * the pyramid actually waits for them.
 *
 * <p>Written from the HTTP executor and the server thread; all maps are
 * concurrent, values immutable.
 */
public final class EscalationStore {

    private EscalationStore() {}

    public record Escalation(String id, String bot, String kind, String question,
                             List<String> options, String directiveJson, long atMillis) {}

    public record Response(String action, String text, long atMillis) {}

    private static final Map<String, Escalation> PENDING = new ConcurrentHashMap<>();
    private static final Map<String, Response> RESPONSES = new ConcurrentHashMap<>();
    private static final int MAX_RESPONSES_KEPT = 200;

    /** Bumped on every change so the overlay broadcaster knows to resend. */
    private static final AtomicLong VERSION = new AtomicLong();

    public static void submit(String id, String bot, String kind, String question,
                              List<String> options) {
        submit(id, bot, kind, question, options, "");
    }

    public static void submit(String id, String bot, String kind, String question,
                              List<String> options, String directiveJson) {
        PENDING.put(id, new Escalation(id, bot, kind, question,
                options == null ? List.of() : List.copyOf(options),
                directiveJson == null ? "" : directiveJson,
                System.currentTimeMillis()));
        VERSION.incrementAndGet();
    }

    /** Player answered. Removes from pending; the agent polls the response. */
    public static boolean respond(String id, String action, String text) {
        Escalation e = PENDING.remove(id);
        if (e == null) return false;
        RESPONSES.put(id, new Response(action, text, System.currentTimeMillis()));
        if (RESPONSES.size() > MAX_RESPONSES_KEPT) {
            RESPONSES.keySet().stream().limit(RESPONSES.size() - MAX_RESPONSES_KEPT)
                    .toList().forEach(RESPONSES::remove);
        }
        VERSION.incrementAndGet();
        return true;
    }

    /** Agent-side poll. Consumes the response. */
    public static Response takeResponse(String id) {
        return RESPONSES.remove(id);
    }

    /** Agent gave up waiting (or the plan died) — drop the question. */
    public static void withdraw(String id) {
        if (PENDING.remove(id) != null) {
            VERSION.incrementAndGet();
        }
    }

    public static List<Escalation> pending() {
        List<Escalation> list = new ArrayList<>(PENDING.values());
        list.sort((a, b) -> Long.compare(a.atMillis(), b.atMillis()));
        return list;
    }

    public static long version() {
        return VERSION.get();
    }
}
