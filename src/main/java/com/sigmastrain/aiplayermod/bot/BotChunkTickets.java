package com.sigmastrain.aiplayermod.bot;

import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.TicketType;
import net.minecraft.world.level.ChunkPos;

import java.util.Comparator;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Keeps the chunks around a bot at ENTITY-TICKING level while the bot exists.
 *
 * <p>Bots are packet ghosts: not in {@code level.players()}, so they hold no
 * player chunk tickets. Their chunks stayed loaded (FULL) but below
 * entity-ticking level, so every entity near a bot was frozen: bullets a bot
 * fired sat mid-air at their spawn point with full velocity (1,780 rounds,
 * 1,780 frozen bullets, 0 hits). {@code /forceload} on the chunk made them all
 * fly instantly.
 *
 * <p>An EXPIRING custom ticket (first attempt, 300-tick timeout refreshed every
 * 100) did NOT confer entity ticking under this chunk system (C2ME), while the
 * non-expiring FORCED ticket did. So this uses a non-expiring ticket type with
 * an explicit lifecycle: added at the bot's chunk, moved when the bot changes
 * chunk, removed when the bot is despawned. Distance 2 → level 31 at the
 * bot's chunk (entity-ticking), exactly what /forceload grants.
 */
public final class BotChunkTickets {

    private BotChunkTickets() {}

    public static final int REFRESH_TICKS = 20;    // re-evaluate position every second
    private static final int DISTANCE = 2;         // level 33 - 2 = 31 (entity-ticking), same as FORCED

    private static final TicketType<ChunkPos> PRESENCE =
            TicketType.create("aiplayermod_presence", Comparator.comparingLong(ChunkPos::toLong));

    private record Held(ServerLevel level, ChunkPos pos) {}
    private static final Map<UUID, Held> HELD = new ConcurrentHashMap<>();

    /** Ensure the bot's current chunk holds the presence ticket; move it if the bot moved. */
    public static void refresh(ServerPlayer bot) {
        if (!(bot.level() instanceof ServerLevel level)) return;
        ChunkPos pos = bot.chunkPosition();
        Held prev = HELD.get(bot.getUUID());
        if (prev != null && prev.level == level && prev.pos.equals(pos)) return;
        if (prev != null) prev.level.getChunkSource().removeRegionTicket(PRESENCE, prev.pos, DISTANCE, prev.pos);
        level.getChunkSource().addRegionTicket(PRESENCE, pos, DISTANCE, pos);
        HELD.put(bot.getUUID(), new Held(level, pos));
    }

    /** Drop the bot's presence ticket (bot despawned / removed). */
    public static void release(ServerPlayer bot) {
        Held prev = HELD.remove(bot.getUUID());
        if (prev != null) prev.level.getChunkSource().removeRegionTicket(PRESENCE, prev.pos, DISTANCE, prev.pos);
    }
}
