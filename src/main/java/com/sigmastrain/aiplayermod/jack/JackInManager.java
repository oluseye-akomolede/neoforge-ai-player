package com.sigmastrain.aiplayermod.jack;

import com.mojang.authlib.GameProfile;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundPlayerInfoRemovePacket;
import net.minecraft.network.protocol.game.ClientboundPlayerInfoUpdatePacket;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ClientInformation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.Level;
import net.minecraft.world.phys.Vec3;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Jack-in: the player leaves their body and rides a bot's eyes.
 *
 * <p>The husk is the price of admission. On jack-in a REAL player entity —
 * inserted into the level with {@code addNewPlayer}, unlike the bots' packet
 * ghosts — is left standing where the player stood, wearing their skin,
 * holding their health. It does not fight back. It does not move. Because it
 * is in {@code level.players()}, mobs both target it AND spawn around it:
 * an abandoned body makes the night dangerous, which is the point.
 *
 * <p>The real player rides the vanilla spectate path ({@code setCamera}) to
 * the bot — cross-dimension chunk streaming handled entirely by vanilla.
 * Damage to the husk mirrors to the player's health bar live. If the husk
 * dies, the player is snapped back into their body and dies in it, drops
 * where the body stood. No auto-eject on damage; vulnerability is the
 * mechanic (user directive).
 */
public final class JackInManager {

    private JackInManager() {}

    public record Session(UUID playerId, String botName, ServerPlayer husk,
                          GameType previousMode, long startedAt) {}

    private static final Map<UUID, Session> SESSIONS = new ConcurrentHashMap<>();

    /** Camera re-assert delay: the client needs the bot entity before the
     *  camera packet can bind to it after a dimension switch. */
    private static final int CAMERA_REASSERT_TICKS = 10;
    private static final Map<UUID, Integer> PENDING_REASSERT = new ConcurrentHashMap<>();

    public static boolean isJackedIn(UUID playerId) {
        return SESSIONS.containsKey(playerId);
    }

    public static Session session(UUID playerId) {
        return SESSIONS.get(playerId);
    }

    // ── jack in ──────────────────────────────────────────────────────────

    public static String jackIn(ServerPlayer sp, String botName) {
        if (SESSIONS.containsKey(sp.getUUID())) {
            return "already jacked in — eject first";
        }
        BotPlayer bot = BotManager.getBot(botName);
        if (bot == null || bot.getPlayer() == null || !bot.isAlive()) {
            return "no living bot named " + botName;
        }

        ServerLevel level = sp.serverLevel();
        GameType previous = sp.gameMode.getGameModeForPlayer();

        ServerPlayer husk = spawnHusk(sp, level);
        if (husk == null) {
            return "could not manifest your body-double";
        }

        SESSIONS.put(sp.getUUID(), new Session(
                sp.getUUID(), botName, husk, previous, System.currentTimeMillis()));

        // Spectator first — the client's camera handling assumes it, and it
        // makes the traveling player intangible while out-of-body.
        sp.setGameMode(GameType.SPECTATOR);
        sp.setCamera(bot.getPlayer());          // vanilla: teleports cross-dim + streams chunks
        bot.sendSpawnPackets(sp);               // make sure the client HAS the bot entity
        PENDING_REASSERT.put(sp.getUUID(), CAMERA_REASSERT_TICKS);

        sp.sendSystemMessage(Component.literal(
                "§dYou leave your body behind. §8(" + botName + " · H → overlay · eject to return)"));
        AIPlayerMod.LOGGER.info("[jack] {} -> {} (husk {} at {})",
                sp.getName().getString(), botName,
                husk.getName().getString(), husk.blockPosition().toShortString());
        return null;
    }

    private static ServerPlayer spawnHusk(ServerPlayer sp, ServerLevel level) {
        try {
            String base = sp.getName().getString();
            String huskName = (base.length() > 12 ? base.substring(0, 12) : base) + "_hsk";
            GameProfile profile = new GameProfile(UUID.randomUUID(), huskName);
            // The player's skin, so the body you leave behind is YOURS.
            profile.getProperties().putAll(sp.getGameProfile().getProperties());

            HuskPlayer husk = new HuskPlayer(level.getServer(), level, profile,
                    ClientInformation.createDefault());
            husk.moveTo(sp.getX(), sp.getY(), sp.getZ(), sp.getYRot(), sp.getXRot());
            husk.setHealth(sp.getHealth());
            husk.getFoodData().setFoodLevel(sp.getFoodData().getFoodLevel());

            // Same listener the bots use — packets sent TO the husk go
            // nowhere safely instead of NPEing.
            var connection = new com.sigmastrain.aiplayermod.bot.BotConnection(level.getServer());
            var cookie = net.minecraft.server.network.CommonListenerCookie
                    .createInitial(profile, false);
            new com.sigmastrain.aiplayermod.bot.BotPacketListener(
                    level.getServer(), connection, husk, cookie);

            // Tab entry first so clients will render the player entity, then a
            // REAL level insertion — tracking, collisions, mob targeting, and
            // mob SPAWNING all follow from being in level.players().
            level.getServer().getPlayerList().broadcastAll(
                    new ClientboundPlayerInfoUpdatePacket(
                            ClientboundPlayerInfoUpdatePacket.Action.ADD_PLAYER, husk));
            level.addNewPlayer(husk);

            // Announce the husk as a login. Being in level.players() means
            // OTHER entities' ticks test it against per-player mod state
            // (crash #2: a rctmod TrainerMob's targeting scan NPE'd on the
            // husk's missing PlayerState — no husk-side override can stop a
            // crash in someone else's tick). Every mod initializes that
            // state in the login event, so the husk must announce itself
            // like the real player it impersonates. Packet sends to it go
            // through BotPacketListener and vanish safely. If any handler
            // throws, the husk is unsafe to leave in the level — tear it
            // down and fail the jack-in loudly instead of crashing later.
            try {
                net.neoforged.neoforge.common.NeoForge.EVENT_BUS.post(
                        new net.neoforged.neoforge.event.entity.player.PlayerEvent
                                .PlayerLoggedInEvent(husk));
            } catch (Exception e) {
                AIPlayerMod.LOGGER.error("[jack] a login handler rejected the husk — aborting jack-in", e);
                removeHusk(husk);
                return null;
            }
            return husk;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("[jack] husk spawn failed", e);
            return null;
        }
    }

    // ── eject ────────────────────────────────────────────────────────────

    /** @param died true when the husk was killed — the player dies in-body. */
    public static String eject(ServerPlayer sp, boolean died) {
        Session s = SESSIONS.remove(sp.getUUID());
        if (s == null) return "not jacked in";
        PENDING_REASSERT.remove(sp.getUUID());

        ServerPlayer husk = s.husk();
        ServerLevel huskLevel = husk.serverLevel();
        Vec3 pos = husk.position();
        float health = Math.max(0.5f, husk.getHealth());

        sp.setCamera(null);
        sp.teleportTo(huskLevel, pos.x, pos.y, pos.z, husk.getYRot(), husk.getXRot());
        sp.setGameMode(died ? GameType.SURVIVAL : s.previousMode());

        removeHusk(husk);

        if (died) {
            sp.sendSystemMessage(Component.literal("§4You snap back into a dying body."));
            sp.hurt(sp.damageSources().generic(), Float.MAX_VALUE);
        } else {
            sp.setHealth(Math.min(health, sp.getMaxHealth()));
            sp.sendSystemMessage(Component.literal("§dYou return to your body."));
        }
        AIPlayerMod.LOGGER.info("[jack] {} ejected from {} (died={})",
                sp.getName().getString(), s.botName(), died);
        return null;
    }

    private static void removeHusk(ServerPlayer husk) {
        // Mirror of the login event fired on spawn — lets mods (rctmod's
        // trainer registry, team mods, etc.) release the per-player state
        // they created for the husk instead of leaking it.
        try {
            net.neoforged.neoforge.common.NeoForge.EVENT_BUS.post(
                    new net.neoforged.neoforge.event.entity.player.PlayerEvent
                            .PlayerLoggedOutEvent(husk));
        } catch (Exception e) {
            AIPlayerMod.LOGGER.warn("[jack] husk logout-event issue: {}", e.toString());
        }
        try {
            husk.getServer().getPlayerList().broadcastAll(
                    new ClientboundPlayerInfoRemovePacket(List.of(husk.getUUID())));
            husk.discard();
        } catch (Exception e) {
            AIPlayerMod.LOGGER.warn("[jack] husk cleanup issue: {}", e.toString());
        }
    }

    // ── per-tick upkeep (server thread) ──────────────────────────────────

    public static void tick(MinecraftServer server) {
        if (SESSIONS.isEmpty()) return;
        for (Session s : SESSIONS.values()) {
            try {
                tickSession(server, s);
            } catch (Exception e) {
                // A jack-in session must never be able to take the server
                // down (it did once — rctmod NPE on the ticking husk).
                // Fail the SESSION, keep the server.
                AIPlayerMod.LOGGER.error("[jack] session error for {} — force ejecting",
                        s.botName(), e);
                ServerPlayer sp = server.getPlayerList().getPlayer(s.playerId());
                try {
                    if (sp != null) eject(sp, false);
                    else {
                        SESSIONS.remove(s.playerId());
                        removeHusk(s.husk());
                    }
                } catch (Exception cleanup) {
                    SESSIONS.remove(s.playerId());
                }
            }
        }
    }

    private static void tickSession(MinecraftServer server, Session s) {
        {
            ServerPlayer sp = server.getPlayerList().getPlayer(s.playerId());
            if (sp == null) return; // logout event handles it

            ServerPlayer husk = s.husk();

            // Husk died between events? Belt and braces — the death event is
            // primary, this is the fallback.
            if (!husk.isAlive()) {
                eject(sp, true);
                return;
            }

            // Bot vanished (despawn/death) — nothing left to inhabit.
            BotPlayer bot = BotManager.getBot(s.botName());
            if (bot == null || !bot.isAlive()) {
                sp.sendSystemMessage(Component.literal("§cThe link collapses — " +
                        s.botName() + " is gone."));
                eject(sp, false);
                return;
            }

            // Mirror the body's pain to the traveler's health bar, live.
            if (Math.abs(sp.getHealth() - husk.getHealth()) > 0.01f) {
                boolean dropped = husk.getHealth() < sp.getHealth();
                sp.setHealth(Math.max(0.5f, Math.min(husk.getHealth(), sp.getMaxHealth())));
                if (dropped) {
                    sp.displayClientMessage(Component.literal(
                            String.format("§c⚠ your body is taking damage — %.0f♥ left", husk.getHealth() / 2)),
                            true);
                }
            }

            // The body wanders; the traveler follows. If the bot crossed
            // into another dimension (live repro: TELEPORT to the End
            // while jacked), the camera packet binds to an entity the
            // client cannot see and the view wedges. Spectator semantics:
            // move the player to the bot's level, then let the re-assert
            // loop below re-bind the camera once the entity streams in.
            ServerPlayer body = bot.getPlayer();
            if (sp.level() != body.level()) {
                sp.teleportTo((net.minecraft.server.level.ServerLevel) body.level(),
                        body.getX(), body.getY(), body.getZ(),
                        body.getYRot(), body.getXRot());
                PENDING_REASSERT.put(s.playerId(), 1);
                sp.displayClientMessage(Component.literal(
                        "§d⇢ following " + s.botName() + " into "
                                + body.level().dimension().location().getPath()), true);
            }

            // Camera re-assert, continuously — and via the RAW packet.
            // Second live test proved setCamera() useless here: vanilla only
            // sends ClientboundSetCameraPacket when the camera target
            // CHANGES, and server-side it's already the bot, so re-calling
            // it re-sends nothing and the client that missed the first
            // packet (entity not streamed yet) stays locked inside the
            // bot's head forever. Send spawn packets then the camera packet
            // directly, once a second; both are idempotent client-side.
            Integer left = PENDING_REASSERT.merge(s.playerId(), -1, Integer::sum);
            if (left == null || left <= 0) {
                PENDING_REASSERT.put(s.playerId(), 20);
                bot.sendSpawnPackets(sp);
                sp.connection.send(new net.minecraft.network.protocol.game
                        .ClientboundSetCameraPacket(bot.getPlayer()));
            }
        }
    }

    // ── event hooks (called from OverlayNetwork.ServerEvents) ────────────

    /** True when this entity is someone's husk. */
    public static Session sessionForHusk(Player entity) {
        for (Session s : SESSIONS.values()) {
            if (s.husk() == entity) return s;
        }
        return null;
    }

    public static void onHuskDeath(Session s, MinecraftServer server) {
        ServerPlayer sp = server.getPlayerList().getPlayer(s.playerId());
        if (sp != null) {
            eject(sp, true);
        } else {
            removeHusk(s.husk());
            SESSIONS.remove(s.playerId());
        }
    }

    public static void onPlayerLogout(ServerPlayer sp) {
        if (SESSIONS.containsKey(sp.getUUID())) {
            // Restore the body before the player entity is saved — they must
            // wake up where they left themselves, not floating at the bot.
            eject(sp, false);
        }
    }

    public static void ejectAll(MinecraftServer server) {
        for (UUID id : SESSIONS.keySet().toArray(new UUID[0])) {
            ServerPlayer sp = server.getPlayerList().getPlayer(id);
            if (sp != null) eject(sp, false);
            else {
                Session s = SESSIONS.remove(id);
                if (s != null) removeHusk(s.husk());
            }
        }
    }

    // ── overlay status ───────────────────────────────────────────────────

    public static Map<String, Object> statusFor(ServerPlayer sp) {
        Session s = SESSIONS.get(sp.getUUID());
        if (s == null) return Map.of("active", false);
        ServerPlayer husk = s.husk();
        ResourceKey<Level> dim = husk.level().dimension();
        BlockPos p = husk.blockPosition();
        return Map.of("active", true, "bot", s.botName(),
                "husk_health", husk.getHealth(),
                "x", p.getX(), "y", p.getY(), "z", p.getZ(),
                "dimension", dim.location().toString());
    }
}
