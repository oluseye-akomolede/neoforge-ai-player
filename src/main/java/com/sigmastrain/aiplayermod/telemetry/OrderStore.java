package com.sigmastrain.aiplayermod.telemetry;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Orders — the other half of the Talk/Order split.
 *
 * <p>Talk is conversation; an order becomes a plan. The overlay's directive
 * builder (and, in v8, the equipment-window chat) enqueues here; the agent
 * polls, routes each order through {@code plan_orchestrator.execute_task},
 * and reports status back. Because orders ride the same orchestrator as chat
 * tasks, every L4 escalation trigger applies to them for free.
 *
 * <p>The mod is the mailbox, not the brain — same contract as
 * {@link TalkStore}. Status lines exist so the overlay can answer "did my
 * order land?" honestly instead of leaving the player to infer it from the
 * Mind tab.
 */
public final class OrderStore {

    private OrderStore() {}

    /**
     * @param kind   directive kind ("MINE") for builder orders, or "TEXT"
     *               for free-text orders (v8 equipment chat)
     * @param params JSON object string — builder field values, or
     *               {@code {"text": "..."}} for TEXT orders
     */
    public record Order(String id, String bot, String player, String kind,
                        String params, String fleetId, long atMillis) {}

    public record OrderStatus(String id, String bot, String kind,
                              String status, String detail, String fleetId,
                              long atMillis) {}

    private static final int MAX_PENDING = 20;
    private static final int MAX_STATUS_PER_BOT = 10;

    private static final Deque<Order> PENDING = new ArrayDeque<>();
    private static final Map<String, Deque<OrderStatus>> STATUS = new ConcurrentHashMap<>();
    private static final AtomicLong SEQ = new AtomicLong();

    /** Bots whose order status changed since the last overlay forward. */
    private static final Map<String, Long> DIRTY = new ConcurrentHashMap<>();

    /** @return the order id, or null when the queue is full (honest refusal). */
    public static String submit(String bot, String player, String kind, String params) {
        return submit(bot, player, kind, params, "");
    }

    public static String submit(String bot, String player, String kind, String params,
                                String fleetId) {
        synchronized (PENDING) {
            if (PENDING.size() >= MAX_PENDING) return null;
            String id = "o" + SEQ.incrementAndGet();
            PENDING.addLast(new Order(id, bot, player, kind, params,
                    fleetId == null ? "" : fleetId, System.currentTimeMillis()));
            setStatus(id, bot, kind, "QUEUED", "waiting for agent", fleetId);
            return id;
        }
    }

    private static final AtomicLong FLEET_SEQ = new AtomicLong();

    public static String nextFleetId() {
        return "f" + FLEET_SEQ.incrementAndGet();
    }

    /** Agent poll: drain everything pending. */
    public static List<Order> drainPending() {
        synchronized (PENDING) {
            List<Order> out = new ArrayList<>(PENDING);
            PENDING.clear();
            return out;
        }
    }

    /** Agent reports progress: QUEUED → RUNNING → COMPLETED/FAILED. */
    public static void setStatus(String id, String bot, String kind,
                                 String status, String detail) {
        String fleetId = "";
        Deque<OrderStatus> q0 = STATUS.get(bot);
        if (q0 != null) {
            synchronized (q0) {
                for (OrderStatus s : q0) {
                    if (s.id().equals(id)) {
                        fleetId = s.fleetId();
                        break;
                    }
                }
            }
        }
        setStatus(id, bot, kind, status, detail, fleetId);
    }

    public static void setStatus(String id, String bot, String kind,
                                 String status, String detail, String fleetId) {
        Deque<OrderStatus> q = STATUS.computeIfAbsent(bot, k -> new ArrayDeque<>());
        synchronized (q) {
            q.removeIf(s -> s.id().equals(id));
            q.addLast(new OrderStatus(id, bot, kind, status,
                    detail.length() > 200 ? detail.substring(0, 200) : detail,
                    fleetId == null ? "" : fleetId, System.currentTimeMillis()));
            while (q.size() > MAX_STATUS_PER_BOT) q.removeFirst();
        }
        DIRTY.put(bot, System.currentTimeMillis());
    }

    public static List<OrderStatus> statuses(String bot) {
        Deque<OrderStatus> q = STATUS.get(bot);
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
}
