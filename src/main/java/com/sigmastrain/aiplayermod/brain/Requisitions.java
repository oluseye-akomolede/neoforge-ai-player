package com.sigmastrain.aiplayermod.brain;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Extension seam: a bot running {@code REQUISITION} posts a request here and
 * waits; a supplier mod (hive) polls {@link #pending()}, does whatever the
 * request costs on its own ledger, and calls {@link #complete}. aiplayermod
 * itself is economy-agnostic — it neither knows nor cares what a requisition
 * costs, exactly like {@code CULTIVATE} leaves FE to hive.
 *
 * <p>Request kinds: {@code vehicle:<entity id or name>} and plain item ids.
 */
public final class Requisitions {

    private Requisitions() {}

    /** A live request. {@code kind} = "vehicle" | "item"; {@code what} = the id/name asked for. */
    public record Request(String bot, String kind, String what, int count, long postedGameTime) {}

    /** How a request ended. */
    public record Outcome(boolean ok, String message, String detail) {}

    private static final Map<String, Request> PENDING = new ConcurrentHashMap<>();
    private static final Map<String, Outcome> DONE = new ConcurrentHashMap<>();
    /** Requests a supplier has claimed (so two suppliers don't both fulfil). */
    private static final Map<String, String> CLAIMED = new ConcurrentHashMap<>();

    public static void post(Request r) {
        DONE.remove(r.bot());
        CLAIMED.remove(r.bot());
        PENDING.put(r.bot(), r);
    }

    public static void cancel(String bot) {
        PENDING.remove(bot);
        CLAIMED.remove(bot);
    }

    /** Snapshot of unclaimed, pending requests. */
    public static List<Request> pending() {
        List<Request> out = new ArrayList<>();
        for (Request r : PENDING.values()) {
            if (!CLAIMED.containsKey(r.bot())) out.add(r);
        }
        return out;
    }

    /** A supplier takes ownership of a request. Returns false if already claimed/gone. */
    public static boolean claim(String bot, String supplier) {
        if (!PENDING.containsKey(bot)) return false;
        return CLAIMED.putIfAbsent(bot, supplier) == null;
    }

    /** Supplier reports the result; the waiting behavior picks it up next tick. */
    public static void complete(String bot, boolean ok, String message, String detail) {
        PENDING.remove(bot);
        CLAIMED.remove(bot);
        DONE.put(bot, new Outcome(ok, message == null ? "" : message, detail == null ? "" : detail));
    }

    /** Behavior side: consume the outcome once. */
    public static Outcome take(String bot) {
        return DONE.remove(bot);
    }

    public static Request pendingFor(String bot) {
        return PENDING.get(bot);
    }
}
