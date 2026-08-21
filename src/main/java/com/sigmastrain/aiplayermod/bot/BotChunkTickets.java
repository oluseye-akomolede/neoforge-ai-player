package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.SectionPos;
import net.minecraft.server.level.DistanceManager;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Makes a bot anchor its surroundings the way a REAL player does, so entities
 * near it actually tick.
 *
 * <p>Bots are packet ghosts: never in {@code level.players()}, so
 * {@code ChunkMap.move(ServerPlayer)} — which registers a real player's section
 * with the {@link DistanceManager} — is never called for them. The result: the
 * bot's chunks are FULL-loaded (blocks/machines tick) but NOT entity-ticking, so
 * every entity near a bot is frozen. Proven with probes: a vanilla arrow with
 * motion and an AI zombie both sat still next to bots; bot-fired bullets hung in
 * the air (thousands fired, zero hits). Custom force-tick chunk tickets did not
 * help because this server runs C2ME's no-tick view distance, which drives
 * entity-ticking chunks from {@code DistanceManager.addPlayer} (its
 * {@code NoTickSystem.addPlayerSource} hook) — a method only real players reach.
 *
 * <p>Fix: call the very methods {@code ChunkMap.move} calls. On the bot's tick we
 * compare its section to the last one and, on a change (or first registration),
 * {@code removePlayer(old)} + {@code addPlayer(new)}. That drives vanilla's
 * {@code PlayerTicketTracker} (the ENTITY_TICKING ticket source), the ticking
 * tracker, AND C2ME's no-tick hook — identical to a real player, minus any
 * client-facing packets (the bot stays a ghost). Released on despawn. All the
 * API used ({@code ServerChunkCache.chunkMap}, {@code getDistanceManager},
 * {@code add/removePlayer}) is public, so no mixin is needed.
 */
public final class BotChunkTickets {

    private BotChunkTickets() {}

    /** Only a section change matters; checking every tick is a cheap comparison. */
    public static final int REFRESH_TICKS = 1;

    private record Held(ServerLevel level, long section) {}
    private static final Map<UUID, Held> HELD = new HashMap<>();

    private static DistanceManager dm(ServerLevel level) {
        return level.getChunkSource().chunkMap.getDistanceManager();
    }

    /** Register/refresh the bot as a player-like ticking source at its section. Server thread only. */
    public static synchronized void refresh(ServerPlayer bot) {
        if (!(bot.level() instanceof ServerLevel level)) return;
        SectionPos section = SectionPos.of(bot);
        long key = section.asLong();
        Held prev = HELD.get(bot.getUUID());
        if (prev != null && prev.level == level && prev.section == key) return;

        boolean before = level.isPositionEntityTicking(bot.blockPosition());
        if (prev != null) {
            dm(prev.level).removePlayer(SectionPos.of(prev.section), bot);
        }
        dm(level).addPlayer(section, bot);
        HELD.put(bot.getUUID(), new Held(level, key));
        boolean after = level.isPositionEntityTicking(bot.blockPosition());
        AIPlayerMod.LOGGER.info("[BotChunkTickets] {} anchored section {} in {}: entityTicking {} -> {}",
                bot.getGameProfile().getName(), section.chunk(), level.dimension().location(), before, after);
    }

    /** Drop the bot's player-source registration (bot despawned / removed). */
    public static synchronized void release(ServerPlayer bot) {
        Held prev = HELD.remove(bot.getUUID());
        if (prev != null) {
            try {
                dm(prev.level).removePlayer(SectionPos.of(prev.section), bot);
            } catch (Throwable t) {
                AIPlayerMod.LOGGER.debug("[BotChunkTickets] release failed for {}: {}",
                        bot.getGameProfile().getName(), t.toString());
            }
        }
    }
}
