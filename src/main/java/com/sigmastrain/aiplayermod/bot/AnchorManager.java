package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.TicketType;
import net.minecraft.world.level.ChunkPos;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Chunk anchoring — the fleet exists even when the player doesn't.
 *
 * <p>Bots are packet ghosts: they hold no chunk tickets, so the world goes
 * cold around them the moment the player leaves. Every "mysterious" failure
 * of 2026-08-11 was this — the 4,826-node grid shrinking to one node, a
 * crafting job frozen mid-CPU, wide searches pathing through void. An
 * anchored bot holds a player-grade ticket over a 7×7 region around itself
 * and pays for it in XP: warmth costs, or every bot would anchor forever
 * and the server would pay instead.
 *
 * <p>This is the hive mod's drone-upkeep mechanic in embryo: presence in
 * the world as a metered resource.
 */
public final class AnchorManager {

    private AnchorManager() {}

    private static final TicketType<ChunkPos> ANCHOR_TICKET =
            TicketType.create("aiplayermod_anchor", java.util.Comparator.comparingLong(ChunkPos::toLong));

    /** distance 3 → ticket level 30: the center chunks fully entity-tick. */
    private static final int TICKET_DISTANCE = 3;

    private static final int XP_LEVELS_PER_HOUR = Integer.parseInt(
            System.getenv().getOrDefault("AIPLAYER_ANCHOR_XP_PER_HOUR", "2"));
    private static final int FLEET_ANCHOR_CAP = Integer.parseInt(
            System.getenv().getOrDefault("AIPLAYER_ANCHOR_CAP", "5"));

    /** Ticks per 1-level drain (levels/hr → 72000 ticks/hr ÷ rate). */
    private static final long TICKS_PER_LEVEL_DRAIN =
            XP_LEVELS_PER_HOUR <= 0 ? Long.MAX_VALUE : 72000L / XP_LEVELS_PER_HOUR;

    private static final class Anchor {
        ServerLevel level;
        ChunkPos center;
        long drainAccumulator;
    }

    private static final Map<String, Anchor> ANCHORS = new ConcurrentHashMap<>();

    // ── control ──────────────────────────────────────────────────────────

    /** @return null on success, honest refusal otherwise. */
    public static String enable(BotPlayer bot) {
        ServerPlayer p = bot.getPlayer();
        if (p == null || !bot.isAlive()) return "bot has no living body";
        String name = p.getGameProfile().getName();
        if (ANCHORS.containsKey(name)) return null; // already anchored — fine
        if (ANCHORS.size() >= FLEET_ANCHOR_CAP) {
            return "fleet anchor cap reached (" + FLEET_ANCHOR_CAP
                    + ") — release one first";
        }
        if (p.experienceLevel < 1) {
            return "anchoring costs " + XP_LEVELS_PER_HOUR
                    + " XP levels/hour and this bot is broke - order it to MEDITATE first";
        }
        Anchor a = new Anchor();
        a.level = p.serverLevel();
        a.center = p.chunkPosition();
        a.level.getChunkSource().addRegionTicket(ANCHOR_TICKET, a.center,
                TICKET_DISTANCE, a.center);
        ANCHORS.put(name, a);
        AIPlayerMod.LOGGER.info("[anchor] {} anchored at {} in {}", name,
                a.center, a.level.dimension().location());
        return null;
    }

    public static void disable(BotPlayer bot) {
        ServerPlayer p = bot.getPlayer();
        if (p == null) return;
        Anchor a = ANCHORS.remove(p.getGameProfile().getName());
        if (a != null) {
            a.level.getChunkSource().removeRegionTicket(ANCHOR_TICKET, a.center,
                    TICKET_DISTANCE, a.center);
            AIPlayerMod.LOGGER.info("[anchor] {} released", p.getGameProfile().getName());
        }
    }

    public static boolean isAnchored(String botName) {
        return ANCHORS.containsKey(botName);
    }

    public static int count() {
        return ANCHORS.size();
    }

    public static int xpPerHour() {
        return XP_LEVELS_PER_HOUR;
    }

    // ── per-tick upkeep (server thread, called from BotManager.tick) ─────

    private static long tickCounter = 0;

    public static void tick(MinecraftServer server) {
        if (ANCHORS.isEmpty()) return;
        tickCounter++;

        // Reposition follow: cheap cadence — an anchor trails its bot.
        boolean reposition = tickCounter % 100 == 0;

        for (var entry : ANCHORS.entrySet()) {
            String name = entry.getKey();
            Anchor a = entry.getValue();
            BotPlayer bot = BotManager.getBot(name);
            ServerPlayer p = bot != null ? bot.getPlayer() : null;
            if (p == null || !bot.isAlive()) {
                a.level.getChunkSource().removeRegionTicket(ANCHOR_TICKET, a.center,
                        TICKET_DISTANCE, a.center);
                ANCHORS.remove(name);
                continue;
            }

            if (reposition) {
                ServerLevel nowLevel = p.serverLevel();
                ChunkPos nowPos = p.chunkPosition();
                if (nowLevel != a.level || !nowPos.equals(a.center)) {
                    a.level.getChunkSource().removeRegionTicket(ANCHOR_TICKET, a.center,
                            TICKET_DISTANCE, a.center);
                    nowLevel.getChunkSource().addRegionTicket(ANCHOR_TICKET, nowPos,
                            TICKET_DISTANCE, nowPos);
                    a.level = nowLevel;
                    a.center = nowPos;
                }
            }

            // XP metering: warmth is not free.
            a.drainAccumulator++;
            if (a.drainAccumulator >= TICKS_PER_LEVEL_DRAIN) {
                a.drainAccumulator = 0;
                if (p.experienceLevel >= 1) {
                    p.giveExperienceLevels(-1);
                } else {
                    // Broke: the anchor drops, loudly enough to notice.
                    a.level.getChunkSource().removeRegionTicket(ANCHOR_TICKET, a.center,
                            TICKET_DISTANCE, a.center);
                    ANCHORS.remove(name);
                    bot.systemChat("Out of XP — my anchor has collapsed. "
                            + "The world grows cold around me.", "red");
                    AIPlayerMod.LOGGER.warn("[anchor] {} went broke — anchor dropped", name);
                }
            }
        }
    }

    public static void releaseAll() {
        for (var entry : ANCHORS.entrySet()) {
            Anchor a = entry.getValue();
            a.level.getChunkSource().removeRegionTicket(ANCHOR_TICKET, a.center,
                    TICKET_DISTANCE, a.center);
        }
        ANCHORS.clear();
    }
}
