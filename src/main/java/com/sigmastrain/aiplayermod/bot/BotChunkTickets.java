package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.ChunkPos;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Keeps the chunks around a bot at ENTITY-TICKING level while the bot exists.
 *
 * <p>Bots are packet ghosts: not in {@code level.players()}, so they hold no
 * player chunk tickets. Their chunks stayed loaded (FULL) but below
 * entity-ticking level, so every entity near a bot was frozen — bullets sat
 * mid-air at their spawn point with full velocity (980 rounds → 980 frozen
 * bullets, 0 hits), mobs beside bots never moved.
 *
 * <p>Three custom-ticket variants (expiring, non-expiring, forceTicks=true via
 * addRegionTicket) all failed to confer entity ticking under this chunk system
 * (C2ME), while {@code /forceload} always worked. So this now takes EXACTLY the
 * path /forceload takes — {@link ServerChunkCache#updateChunkForced} — minus
 * the persistent ForcedChunksSavedData entry, with a per-chunk refcount so
 * bots sharing a chunk don't drop each other's ticket. Released on despawn.
 * Every change logs {@code isPositionEntityTicking} so the server log shows
 * the chunk's true state.
 */
public final class BotChunkTickets {

    private BotChunkTickets() {}

    public static final int REFRESH_TICKS = 20;   // re-evaluate position every second

    private record Held(ServerLevel level, ChunkPos pos) {}
    private static final Map<UUID, Held> HELD = new HashMap<>();
    private static final Map<Held, Integer> REFS = new HashMap<>();

    private static void acquire(Held h) {
        int n = REFS.merge(h, 1, Integer::sum);
        if (n == 1) {
            boolean before = h.level.isPositionEntityTicking(h.pos.getWorldPosition());
            h.level.getChunkSource().updateChunkForced(h.pos, true);
            boolean after = h.level.isPositionEntityTicking(h.pos.getWorldPosition());
            AIPlayerMod.LOGGER.info("[BotChunkTickets] force-tick {} in {}: entityTicking {} -> {}",
                    h.pos, h.level.dimension().location(), before, after);
        }
    }

    private static void releaseHeld(Held h) {
        Integer n = REFS.get(h);
        if (n == null) return;
        if (n <= 1) {
            REFS.remove(h);
            h.level.getChunkSource().updateChunkForced(h.pos, false);
            AIPlayerMod.LOGGER.info("[BotChunkTickets] released {} in {}", h.pos, h.level.dimension().location());
        } else {
            REFS.put(h, n - 1);
        }
    }

    /** Ensure the bot's current chunk is force-ticked; move the hold if the bot moved. Server thread. */
    public static synchronized void refresh(ServerPlayer bot) {
        if (!(bot.level() instanceof ServerLevel level)) return;
        Held now = new Held(level, bot.chunkPosition());
        Held prev = HELD.get(bot.getUUID());
        if (now.equals(prev)) return;
        acquire(now);
        if (prev != null) releaseHeld(prev);
        HELD.put(bot.getUUID(), now);
    }

    /** Drop the bot's hold (bot despawned / removed). */
    public static synchronized void release(ServerPlayer bot) {
        Held prev = HELD.remove(bot.getUUID());
        if (prev != null) releaseHeld(prev);
    }
}
