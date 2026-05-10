package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.server.MinecraftServer;

import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

public class BotManager {
    private static MinecraftServer server;
    private static final Map<String, BotPlayer> bots = new ConcurrentHashMap<>();

    public static void init(MinecraftServer srv) {
        server = srv;
    }

    public static void shutdown() {
        Path saveDir = getSaveDir();
        if (saveDir != null) {
            for (BotPlayer bot : bots.values()) {
                bot.saveState(saveDir);
            }
        }
        bots.values().forEach(BotPlayer::remove);
        bots.clear();
        server = null;
    }

    public static MinecraftServer getServer() {
        return server;
    }

    public static BotPlayer spawn(String name) {
        if (bots.containsKey(name)) {
            return bots.get(name);
        }
        if (server == null) {
            throw new IllegalStateException("Server not started");
        }
        BotPlayer bot = BotPlayer.create(server, name);
        Path saveDir = getSaveDir();
        if (saveDir != null) {
            bot.loadState(saveDir);
        }
        bots.put(name, bot);
        AIPlayerMod.LOGGER.info("Spawned bot: {}", name);
        return bot;
    }

    public static void despawn(String name) {
        BotPlayer bot = bots.remove(name);
        if (bot != null) {
            bot.remove();
            AIPlayerMod.LOGGER.info("Despawned bot: {}", name);
        }
    }

    public static BotPlayer getBot(String name) {
        return bots.get(name);
    }

    public static Map<String, BotPlayer> getAllBots() {
        return bots;
    }

    public static void tick() {
        bots.values().forEach(BotPlayer::tickActions);
    }

    private static Path getSaveDir() {
        if (server == null) return null;
        return server.getServerDirectory().resolve("config").resolve("aiplayermod-bots");
    }
}
