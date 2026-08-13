package com.sigmastrain.aiplayermod.telemetry;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Standing orders — the hive's homeostasis.
 *
 * <p>A standing order is a persistent watcher: a condition over observable
 * state ("ME count of matter balls ≥ 10,000"), an action to fire when it
 * breaks, and an honest record of what happened last. The mod is the
 * MAILBOX as always: definitions live here (created from the overlay,
 * edited from the overlay, persisted with the world via BotManager's save
 * hook); the agent polls them, evaluates conditions against the world it
 * can see, fires actions through the ordinary order lane, and reports
 * readings back so the overlay can show "current: 8,214 / want: 10,000".
 *
 * <p>This is the hive mod's drone job-loop in embryo: the fleet maintaining
 * invariants instead of executing one-shot commands.
 */
public final class StandingStore {

    private StandingStore() {}

    public static final int PER_BOT_CAP = Integer.parseInt(
            System.getenv().getOrDefault("AIPLAYER_STANDING_CAP", "4"));

    /**
     * @param watchType  me_count | vault_count | xp_level
     * @param comparator gte | lte
     * @param actionKind directive kind (CRAFT_REQUEST…) or TEXT
     * @param lastResult agent-reported: what happened on the last firing
     * @param reading    agent-reported: latest observed value
     */
    public record Standing(String id, String bot, String watchType, String item,
                           long threshold, String comparator,
                           String actionKind, String actionParams,
                           boolean enabled, long lastFired, String lastResult,
                           long reading) {}

    private static final Map<String, Standing> ORDERS = new ConcurrentHashMap<>();
    private static final AtomicLong SEQ = new AtomicLong();
    private static final AtomicLong VERSION = new AtomicLong();

    public static long version() { return VERSION.get(); }

    /** @return id, or null when the bot is at its cap (honest refusal). */
    public static String create(String bot, String watchType, String item,
                                long threshold, String comparator,
                                String actionKind, String actionParams) {
        long forBot = ORDERS.values().stream().filter(s -> s.bot().equals(bot)).count();
        if (forBot >= PER_BOT_CAP) return null;
        String id = "s" + SEQ.incrementAndGet();
        ORDERS.put(id, new Standing(id, bot, watchType, item, threshold,
                comparator == null || comparator.isEmpty() ? "gte" : comparator,
                actionKind, actionParams == null ? "{}" : actionParams,
                true, 0, "never fired", -1));
        VERSION.incrementAndGet();
        return id;
    }

    public static boolean toggle(String id) {
        Standing s = ORDERS.get(id);
        if (s == null) return false;
        ORDERS.put(id, new Standing(s.id(), s.bot(), s.watchType(), s.item(),
                s.threshold(), s.comparator(), s.actionKind(), s.actionParams(),
                !s.enabled(), s.lastFired(), s.lastResult(), s.reading()));
        VERSION.incrementAndGet();
        return true;
    }

    public static boolean delete(String id) {
        boolean removed = ORDERS.remove(id) != null;
        if (removed) VERSION.incrementAndGet();
        return removed;
    }

    /** Agent report: latest reading + optionally a firing result. */
    public static void report(String id, long reading, Long firedAt, String result) {
        Standing s = ORDERS.get(id);
        if (s == null) return;
        ORDERS.put(id, new Standing(s.id(), s.bot(), s.watchType(), s.item(),
                s.threshold(), s.comparator(), s.actionKind(), s.actionParams(),
                s.enabled(),
                firedAt != null ? firedAt : s.lastFired(),
                result != null ? result : s.lastResult(),
                reading));
        VERSION.incrementAndGet();
    }

    public static List<Standing> all() {
        return new ArrayList<>(ORDERS.values());
    }

    public static List<Standing> forBot(String bot) {
        return ORDERS.values().stream().filter(s -> s.bot().equals(bot)).toList();
    }

    // ── persistence (piggybacks the bot-state save cadence) ──────────────

    public static List<Map<String, Object>> save() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Standing s : ORDERS.values()) {
            out.add(Map.of("id", s.id(), "bot", s.bot(), "watchType", s.watchType(),
                    "item", s.item(), "threshold", s.threshold(),
                    "comparator", s.comparator(), "actionKind", s.actionKind(),
                    "actionParams", s.actionParams(), "enabled", s.enabled()));
        }
        return out;
    }

    public static void load(List<Map<String, Object>> rows) {
        long maxSeq = 0;
        for (Map<String, Object> r : rows) {
            String id = String.valueOf(r.get("id"));
            ORDERS.put(id, new Standing(id,
                    String.valueOf(r.get("bot")),
                    String.valueOf(r.get("watchType")),
                    String.valueOf(r.get("item")),
                    ((Number) r.get("threshold")).longValue(),
                    String.valueOf(r.get("comparator")),
                    String.valueOf(r.get("actionKind")),
                    String.valueOf(r.get("actionParams")),
                    Boolean.TRUE.equals(r.get("enabled")),
                    0, "restored", -1));
            try {
                maxSeq = Math.max(maxSeq, Long.parseLong(id.substring(1)));
            } catch (NumberFormatException ignored) {
            }
        }
        while (SEQ.get() < maxSeq) SEQ.incrementAndGet();
        if (!rows.isEmpty()) VERSION.incrementAndGet();
    }
}
