package com.sigmastrain.aiplayermod.client.overlay;

import com.sigmastrain.aiplayermod.network.OverlayPayloads;
import net.minecraft.client.Minecraft;

import java.util.List;

/**
 * Client-side cache of the latest fleet snapshot.
 *
 * <p>Loaded lazily: the payload handlers reference this class from lambda
 * BODIES, so a dedicated server never classloads it. Everything here runs on
 * the client main thread (payload handlers use {@code enqueueWork}).
 */
public final class OverlayClientState {

    private OverlayClientState() {}

    private static OverlayPayloads.FleetSnapshot latest =
            new OverlayPayloads.FleetSnapshot(0, List.of());
    private static long lastUpdateMillis = 0;
    private static String lastAck = "";
    private static long lastAckMillis = 0;

    public static void acceptSnapshot(OverlayPayloads.FleetSnapshot snapshot) {
        latest = snapshot;
        lastUpdateMillis = System.currentTimeMillis();
        Minecraft mc = Minecraft.getInstance();
        if (mc.screen instanceof OverlayScreen screen) {
            screen.onSnapshot(snapshot);
        }
    }

    public static void acceptAck(OverlayPayloads.ControlAck ack) {
        lastAck = (ack.ok() ? "" : "✖ ") + ack.message();
        lastAckMillis = System.currentTimeMillis();
    }

    private static OverlayPayloads.VaultSnapshot vault;
    private static OverlayPayloads.ChannelQuoteReply quote;

    public static void acceptVault(OverlayPayloads.VaultSnapshot snap) {
        vault = snap;
        Minecraft mc = Minecraft.getInstance();
        if (mc.screen instanceof OverlayScreen screen) {
            screen.onVault(snap);
        }
    }

    public static void acceptQuote(OverlayPayloads.ChannelQuoteReply reply) {
        quote = reply;
        Minecraft mc = Minecraft.getInstance();
        if (mc.screen instanceof OverlayScreen screen) {
            screen.onQuote(reply);
        }
    }

    public static OverlayPayloads.VaultSnapshot vault() { return vault; }
    public static OverlayPayloads.ChannelQuoteReply quote() { return quote; }

    // Thought streams, newest LAST (append order); the screen renders
    // newest-first so nothing ever auto-scrolls.
    private static final java.util.Map<String, java.util.List<OverlayPayloads.Thought>> thoughts =
            new java.util.HashMap<>();
    private static final int MAX_THOUGHTS = 120;

    public static void acceptThoughts(OverlayPayloads.ThoughtBatch batch) {
        java.util.List<OverlayPayloads.Thought> list =
                thoughts.computeIfAbsent(batch.bot(), k -> new java.util.ArrayList<>());
        if (batch.full()) list.clear();
        list.addAll(batch.thoughts());
        while (list.size() > MAX_THOUGHTS) list.remove(0);
        Minecraft mc = Minecraft.getInstance();
        if (mc.screen instanceof OverlayScreen screen) {
            screen.onThoughts(batch.bot());
        }
    }

    public static List<OverlayPayloads.Thought> thoughtsFor(String bot) {
        return thoughts.getOrDefault(bot, List.of());
    }

    private static OverlayPayloads.InboxState inbox =
            new OverlayPayloads.InboxState(List.of());

    public static void acceptInbox(OverlayPayloads.InboxState state) {
        inbox = state;
        Minecraft mc = Minecraft.getInstance();
        if (mc.screen instanceof OverlayScreen screen) {
            screen.onInbox(state);
        }
    }

    public static OverlayPayloads.InboxState inbox() { return inbox; }

    private static final java.util.Map<String, List<OverlayPayloads.TalkLine>> talk =
            new java.util.HashMap<>();

    public static void acceptTalk(OverlayPayloads.TalkHistory history) {
        talk.put(history.bot(), history.lines());
        Minecraft mc = Minecraft.getInstance();
        if (mc.screen instanceof OverlayScreen screen) {
            screen.onTalk(history.bot());
        }
    }

    public static List<OverlayPayloads.TalkLine> talkFor(String bot) {
        return talk.getOrDefault(bot, List.of());
    }

    private static OverlayPayloads.JackState jackState =
            new OverlayPayloads.JackState(false, "", 0, 0, 0, 0, "");
    private static long jackStateAt = 0;

    public static void acceptJackState(OverlayPayloads.JackState state) {
        jackState = state;
        jackStateAt = System.currentTimeMillis();
    }

    public static OverlayPayloads.JackState jackState() {
        // Stale tether = assume ejected (server restart mid-session, etc.).
        if (jackState.active() && System.currentTimeMillis() - jackStateAt > 5000) {
            return new OverlayPayloads.JackState(false, "", 0, 0, 0, 0, "");
        }
        return jackState;
    }

    public static boolean isJackedIn() { return jackState().active(); }

    // ── Phase 7: schemas + orders ────────────────────────────────────────

    private static OverlayPayloads.SchemaPush schemas;

    public static void acceptSchemas(OverlayPayloads.SchemaPush push) {
        schemas = push;
    }

    /** Raw schema JSON, or "" until the agent has pushed one. */
    public static String schemasJson() {
        return schemas == null ? "" : schemas.json();
    }

    private static final java.util.Map<String, List<OverlayPayloads.OrderLine>> orders =
            new java.util.HashMap<>();

    public static void acceptOrders(OverlayPayloads.OrderStatusBatch batch) {
        orders.put(batch.bot(), batch.orders());
        Minecraft mc = Minecraft.getInstance();
        if (mc.screen instanceof OverlayScreen screen) {
            screen.onOrders(batch.bot());
        }
    }

    public static List<OverlayPayloads.OrderLine> ordersFor(String bot) {
        return orders.getOrDefault(bot, List.of());
    }

    private static final java.util.Map<String, List<OverlayPayloads.StandingEntry>> standing =
            new java.util.HashMap<>();

    public static void acceptStanding(OverlayPayloads.StandingList list) {
        standing.put(list.bot(), list.orders());
        Minecraft mc = Minecraft.getInstance();
        if (mc.screen instanceof OverlayScreen screen) {
            screen.onStanding(list.bot());
        }
    }

    public static List<OverlayPayloads.StandingEntry> standingFor(String bot) {
        return standing.getOrDefault(bot, List.of());
    }

    /** 0 = agent alive; else seconds it has been silent (server-computed). */
    public static int agentSilentSeconds() {
        return latest.agentSilentSeconds();
    }

    public static OverlayPayloads.FleetSnapshot snapshot() { return latest; }

    /** Milliseconds since the last snapshot arrived — the staleness indicator. */
    public static long ageMillis() {
        return lastUpdateMillis == 0 ? Long.MAX_VALUE
                : System.currentTimeMillis() - lastUpdateMillis;
    }

    /** Recent ack line, or "" once it has aged out. */
    public static String recentAck() {
        return System.currentTimeMillis() - lastAckMillis < 4000 ? lastAck : "";
    }
}
