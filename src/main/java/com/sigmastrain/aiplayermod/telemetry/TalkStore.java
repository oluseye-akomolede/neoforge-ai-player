package com.sigmastrain.aiplayermod.telemetry;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Talk — conversation with a bot's L3, kept apart from orders.
 *
 * <p>Until now every sentence a player typed became a plan; casual remarks
 * spawned orchestrator runs. Talk is the other lane: the overlay (or the web
 * dashboard) posts a message here, the agent polls it, runs a single
 * conversational L3 call — persona, world state, memory, no plan, no
 * dispatch — and posts the reply back.
 *
 * <p>The mod is the mailbox, not the brain: it holds the pending queue and a
 * short per-bot transcript for the overlay to render.
 */
public final class TalkStore {

    private TalkStore() {}

    public record TalkLine(long atMillis, String who, String text) {}

    public record PendingMsg(String id, String bot, String player, String text) {}

    private static final int MAX_HISTORY_PER_BOT = 30;
    private static final int MAX_PENDING = 50;

    private static final Map<String, Deque<TalkLine>> HISTORY = new ConcurrentHashMap<>();
    private static final Deque<PendingMsg> PENDING = new ArrayDeque<>();
    private static final AtomicLong SEQ = new AtomicLong();

    /** Bots whose transcript changed since the last overlay forward. */
    private static final Map<String, Long> DIRTY = new ConcurrentHashMap<>();

    public static void playerMessage(String bot, String player, String text) {
        appendHistory(bot, player, text);
        synchronized (PENDING) {
            PENDING.addLast(new PendingMsg(
                    "t" + SEQ.incrementAndGet(), bot, player, text));
            while (PENDING.size() > MAX_PENDING) PENDING.removeFirst();
        }
    }

    public static void botReply(String bot, String text) {
        appendHistory(bot, bot, text);
    }

    /** Agent poll: drain everything pending. */
    public static List<PendingMsg> drainPending() {
        synchronized (PENDING) {
            List<PendingMsg> out = new ArrayList<>(PENDING);
            PENDING.clear();
            return out;
        }
    }

    public static List<TalkLine> history(String bot) {
        Deque<TalkLine> q = HISTORY.get(bot);
        if (q == null) return List.of();
        synchronized (q) {
            return new ArrayList<>(q);
        }
    }

    public static List<String> drainDirty() {
        if (DIRTY.isEmpty()) return List.of();
        List<String> bots = new ArrayList<>(DIRTY.keySet());
        for (String b : bots) DIRTY.remove(b);
        return bots;
    }

    private static void appendHistory(String bot, String who, String text) {
        Deque<TalkLine> q = HISTORY.computeIfAbsent(bot, k -> new ArrayDeque<>());
        synchronized (q) {
            q.addLast(new TalkLine(System.currentTimeMillis(), who,
                    text.length() > 1500 ? text.substring(0, 1500) : text));
            while (q.size() > MAX_HISTORY_PER_BOT) q.removeFirst();
        }
        DIRTY.put(bot, System.currentTimeMillis());
    }
}
