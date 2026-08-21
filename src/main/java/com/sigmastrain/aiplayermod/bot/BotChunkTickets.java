package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.ChunkPos;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Force-ticks a small radius of chunks around each bot so entities near it
 * actually tick.
 *
 * <p>Bots are packet ghosts: never in {@code level.players()}, so nothing drives
 * their surroundings to ENTITY_TICKING and every entity near a bot freezes — a
 * vanilla arrow with motion and an AI zombie both sat still next to bots, and
 * bot-fired bullets hung in the air (thousands fired, zero hits). This server
 * runs C2ME's chunk-system rewrite, under which vanilla's player/ticking tickets
 * (what {@code DistanceManager.addPlayer} feeds) do NOT confer entity ticking —
 * but {@code /forceload} (→ {@link net.minecraft.server.level.ServerChunkCache
 * #updateChunkForced}) does: an RCON forceload of a single bot chunk made an AI
 * zombie in it path immediately.
 *
 * <p>A single chunk under the bot is not enough: combat TELEPORTS the bot chunk
 * to chunk, and a bullet leaves its origin chunk within a tick — so we force a
 * {@code (2R+1)²} block of chunks around the bot ({@code R=}{@value #RADIUS}),
 * covering the short flight of a bullet even as the bot hops. Every forced chunk
 * is REFERENCE-COUNTED across all bots (a {@code FORCED} ticket is not itself
 * refcounted, so two bots sharing a chunk must not let one's release drop it):
 * a chunk is forced on 0→1 refs and released on 1→0. Fully released on despawn.
 */
public final class BotChunkTickets {

    private BotChunkTickets() {}

    public static final int REFRESH_TICKS = 5;   // re-evaluate the footprint 4x/second
    private static final int RADIUS = 2;         // 5x5 chunks — covers a bullet's flight

    private record Chunk(ServerLevel level, long pos) {}
    private static final Map<UUID, Set<Chunk>> HELD = new HashMap<>();
    private static final Map<Chunk, Integer> REFS = new HashMap<>();

    private static void acquire(Chunk c) {
        if (REFS.merge(c, 1, Integer::sum) == 1) {
            c.level.getChunkSource().updateChunkForced(new ChunkPos(c.pos), true);
        }
    }

    private static void releaseChunk(Chunk c) {
        Integer n = REFS.get(c);
        if (n == null) return;
        if (n <= 1) {
            REFS.remove(c);
            c.level.getChunkSource().updateChunkForced(new ChunkPos(c.pos), false);
        } else {
            REFS.put(c, n - 1);
        }
    }

    /** Force-tick the (2R+1)² chunks around the bot; drop chunks it no longer covers. Server thread only. */
    public static synchronized void refresh(ServerPlayer bot) {
        if (!(bot.level() instanceof ServerLevel level)) return;
        ChunkPos center = bot.chunkPosition();
        Set<Chunk> want = new HashSet<>();
        for (int dx = -RADIUS; dx <= RADIUS; dx++) {
            for (int dz = -RADIUS; dz <= RADIUS; dz++) {
                want.add(new Chunk(level, new ChunkPos(center.x + dx, center.z + dz).toLong()));
            }
        }
        Set<Chunk> have = HELD.computeIfAbsent(bot.getUUID(), k -> new HashSet<>());
        if (have.equals(want)) return;
        boolean firstEver = have.isEmpty();
        for (Chunk c : want) if (!have.contains(c)) acquire(c);
        for (Chunk c : have) if (!want.contains(c)) releaseChunk(c);
        HELD.put(bot.getUUID(), want);
        if (firstEver) {
            AIPlayerMod.LOGGER.info("[BotChunkTickets] {} force-ticking {} chunks around {} in {}",
                    bot.getGameProfile().getName(), want.size(), center, level.dimension().location());
        }
    }

    /** Release every chunk this bot was force-ticking (bot despawned / removed). */
    public static synchronized void release(ServerPlayer bot) {
        Set<Chunk> have = HELD.remove(bot.getUUID());
        if (have != null) for (Chunk c : have) releaseChunk(c);
    }
}
