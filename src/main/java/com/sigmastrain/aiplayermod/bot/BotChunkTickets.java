package com.sigmastrain.aiplayermod.bot;

import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.TicketType;
import net.minecraft.world.level.ChunkPos;

import java.util.Comparator;

/**
 * Keeps the chunks around a bot at ENTITY-TICKING level while the bot exists.
 *
 * <p>Bots are packet ghosts: not in {@code level.players()}, so they hold no
 * player chunk tickets. Their chunks stayed loaded (FULL) but below
 * entity-ticking level, so every entity near a bot was frozen: bullets a bot
 * fired sat mid-air at their spawn point with full velocity (3,320 rounds,
 * 0 hits), husks four blocks away never moved. Force-loading the chunk made
 * the frozen bullets fly instantly. The combat ticket ({@code aiplayermod_bot})
 * has a 10 s timeout and was added once — it lapsed ten seconds into every
 * fight.
 *
 * <p>This ticket is re-added every {@value #REFRESH_TICKS} ticks from the bot
 * tick with a {@value #TIMEOUT_TICKS}-tick expiry, so it slides with the bot
 * and lapses on its own when the bot is gone. Distance 3 → level 30 at the
 * bot's chunk (entity-ticking out to the neighbours), a 5x5 footprint — a
 * fraction of one player's simulation distance.
 */
public final class BotChunkTickets {

    private BotChunkTickets() {}

    public static final int REFRESH_TICKS = 100;   // 5 s
    public static final int TIMEOUT_TICKS = 300;   // 15 s — outlives one missed refresh
    private static final int DISTANCE = 3;         // level 33 - 3 = 30 (entity-ticking)

    private static final TicketType<ChunkPos> PRESENCE =
            TicketType.create("aiplayermod_presence", Comparator.comparingLong(ChunkPos::toLong), TIMEOUT_TICKS);

    /** Refresh the entity-ticking ticket at the bot's current chunk. Cheap; call every REFRESH_TICKS. */
    public static void refresh(ServerPlayer bot) {
        if (!(bot.level() instanceof ServerLevel level)) return;
        ChunkPos pos = bot.chunkPosition();
        level.getChunkSource().addRegionTicket(PRESENCE, pos, DISTANCE, pos);
    }
}
