package com.sigmastrain.aiplayermod.bot;

import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * A bot's "master": the real player it answers to. Set to whoever last gave the
 * bot a direct order (chat / inject_chat / a directly-addressed order), so
 * "follow me", "come to me" and the like resolve to a person even when the LLM
 * emits the literal word "me". Hive units fall back to their reservoir owner.
 *
 * <p>In-memory and best-effort — a bot with no recorded master follows/serves
 * the nearest online player. Never used to pick combat targets; only to protect
 * the master from friendly fire and to resolve self-referential order targets.
 */
public final class BotOwners {

    private BotOwners() {}

    private static final Map<String, String> MASTER = new ConcurrentHashMap<>();

    /** Record that {@code playerName} commanded {@code botName} (real players only). */
    public static void setMaster(String botName, String playerName) {
        if (botName == null || playerName == null || playerName.isBlank()) return;
        if (BotManager.getBot(playerName) != null) return;   // a bot is not a master
        MASTER.put(botName, playerName);
    }

    public static String masterName(String botName) {
        return MASTER.get(botName);
    }

    /** Resolve the bot's master to an online player, else null. */
    public static ServerPlayer master(ServerLevel level, String botName) {
        String name = MASTER.get(botName);
        if (name == null) return null;
        return level.getServer().getPlayerList().getPlayerByName(name);
    }

    /** Is this the word a self-referential FOLLOW/GOTO target uses for "my master"? */
    public static boolean isSelfReference(String target) {
        if (target == null) return true;
        String t = target.trim().toLowerCase(java.util.Locale.ROOT);
        return t.isEmpty() || t.equals("me") || t.equals("master") || t.equals("owner")
                || t.equals("my master") || t.equals("the player") || t.equals("player")
                || t.equals("commander") || t.equals("self") || t.equals("you");
    }
}
