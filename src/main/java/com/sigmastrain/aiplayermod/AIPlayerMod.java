package com.sigmastrain.aiplayermod;

import com.sigmastrain.aiplayermod.api.HttpApiServer;
import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.shop.BotShop;
import com.sigmastrain.aiplayermod.shop.EnchantmentRegistry;
import com.sigmastrain.aiplayermod.shop.TransmuteRegistry;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.ModContainer;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.RegisterCommandsEvent;
import net.neoforged.neoforge.event.ServerChatEvent;
import net.neoforged.neoforge.event.entity.player.PlayerEvent;
import net.neoforged.neoforge.event.entity.player.PlayerInteractEvent;
import net.neoforged.neoforge.event.server.ServerStartedEvent;
import net.neoforged.neoforge.event.server.ServerStoppingEvent;
import net.neoforged.neoforge.event.tick.ServerTickEvent;
import com.sigmastrain.aiplayermod.bot.BotEquipmentMenu;
import com.sigmastrain.aiplayermod.bot.BotSelectionMenu;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.network.chat.Component;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;

@Mod(AIPlayerMod.MOD_ID)
public class AIPlayerMod {
    public static final String MOD_ID = "aiplayermod";
    public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

    private static final int DEFAULT_API_PORT = 3100;
    private static final int SPAWN_PACKET_DELAY_TICKS = 40;

    private HttpApiServer apiServer;
    private final Queue<PendingSpawn> pendingSpawns = new ConcurrentLinkedQueue<>();

    private record PendingSpawn(net.minecraft.server.level.ServerPlayer joiner, long sendAtTick) {}

    public AIPlayerMod(IEventBus modEventBus, ModContainer modContainer) {
        NeoForge.EVENT_BUS.register(this);
        ModMenuTypes.MENUS.register(modEventBus);
        LOGGER.info("AI Player Mod initializing");
    }

    @SubscribeEvent
    public void onServerStarted(ServerStartedEvent event) {
        BotManager.init(event.getServer());
        com.sigmastrain.aiplayermod.compat.guns.GunHandler.register();
        com.sigmastrain.aiplayermod.compat.guns.GunStats.register();
        BotShop.init(event.getServer().getServerDirectory());
        TransmuteRegistry.init(event.getServer().getServerDirectory());
        EnchantmentRegistry.init(event.getServer());
        com.sigmastrain.aiplayermod.brain.skill.SkillRegistry.initSeeds();
        com.sigmastrain.aiplayermod.brain.skill.SkillRegistry.initPersistence(
                event.getServer().getServerDirectory().resolve("aiplayermod_skills.json"));

        int port = Integer.parseInt(System.getProperty("aiplayermod.api.port",
                System.getenv().getOrDefault("AIPLAYER_API_PORT", String.valueOf(DEFAULT_API_PORT))));
        String apiKey = System.getProperty("aiplayermod.api.key",
                System.getenv().getOrDefault("AIPLAYER_API_KEY", ""));

        try {
            java.nio.file.Path f = event.getServer().getServerDirectory()
                    .resolve("aiplayermod_standing.json");
            if (java.nio.file.Files.exists(f)) {
                com.google.gson.Gson gson = new com.google.gson.Gson();
                java.util.List<java.util.Map<String, Object>> rows = gson.fromJson(
                        java.nio.file.Files.readString(f),
                        new com.google.gson.reflect.TypeToken<java.util.List<java.util.Map<String, Object>>>() {}.getType());
                if (rows != null) {
                    com.sigmastrain.aiplayermod.telemetry.StandingStore.load(rows);
                    LOGGER.info("Loaded {} standing orders", rows.size());
                }
            }
        } catch (Exception e) {
            LOGGER.warn("Standing orders load failed", e);
        }

        apiServer = new HttpApiServer(port, apiKey);
        apiServer.start();
        LOGGER.info("AI Player API server started on port {}", port);
    }

    @SubscribeEvent
    public void onServerStopping(ServerStoppingEvent event) {
        com.sigmastrain.aiplayermod.bot.BotChunkTickets.releaseAll();
        if (apiServer != null) {
            apiServer.stop();
        }
        TransmuteRegistry.saveConfig();
        com.sigmastrain.aiplayermod.brain.skill.SkillRegistry.save();
        try {
            java.nio.file.Path f = event.getServer().getServerDirectory()
                    .resolve("aiplayermod_standing.json");
            java.nio.file.Files.writeString(f, new com.google.gson.Gson()
                    .toJson(com.sigmastrain.aiplayermod.telemetry.StandingStore.save()));
        } catch (Exception e) {
            LOGGER.warn("Standing orders save failed", e);
        }
        // Order matters: shutdown() SAVES bot state (including the anchored
        // flag) — releasing anchors first wrote anchored=false every time.
        BotManager.shutdown();
        com.sigmastrain.aiplayermod.bot.AnchorManager.releaseAll();
    }

    @SubscribeEvent
    public void onBotHurt(net.neoforged.neoforge.event.entity.living.LivingIncomingDamageEvent event) {
        // Bots and drones fight monsters, not their operator: any damage
        // whose direct or indirect source is a REAL player is void.
        if (!(event.getEntity() instanceof net.minecraft.server.level.ServerPlayer sp)) return;
        if (!BotManager.isBot(sp)) return;
        var src = event.getSource();
        boolean fromRealPlayer =
                (src.getEntity() instanceof net.minecraft.server.level.ServerPlayer a && !BotManager.isBot(a))
                || (src.getDirectEntity() instanceof net.minecraft.server.level.ServerPlayer d && !BotManager.isBot(d));
        if (fromRealPlayer) event.setCanceled(true);
    }

    @SubscribeEvent
    public void onServerTick(ServerTickEvent.Post event) {
        BotManager.tick();
        com.sigmastrain.aiplayermod.bot.BotAggro.tick();
        com.sigmastrain.aiplayermod.bot.AnchorManager.tick(event.getServer());
        TransmuteRegistry.tickSave(event.getServer().getTickCount());

        long currentTick = event.getServer().getTickCount();
        PendingSpawn pending;
        while ((pending = pendingSpawns.peek()) != null && currentTick >= pending.sendAtTick()) {
            pendingSpawns.poll();
            if (pending.joiner().isAlive() && pending.joiner().connection != null) {
                for (var bot : BotManager.getAllBots().values()) {
                    // Same-dimension only — cross-dimension spawns render
                    // phantom copies of the bot in the joiner's world.
                    if (bot.getPlayer() != null && bot.getPlayer().level().dimension()
                            .equals(pending.joiner().level().dimension())) {
                        bot.sendSpawnPackets(pending.joiner());
                    }
                }
            }
        }
    }

    @SubscribeEvent
    public void onRegisterCommands(RegisterCommandsEvent event) {
        ModCommands.register(event.getDispatcher());
    }

    @SubscribeEvent
    public void onPlayerLoggedIn(PlayerEvent.PlayerLoggedInEvent event) {
        if (event.getEntity() instanceof net.minecraft.server.level.ServerPlayer joiner) {
            long sendAt = joiner.getServer().getTickCount() + SPAWN_PACKET_DELAY_TICKS;
            pendingSpawns.add(new PendingSpawn(joiner, sendAt));
        }
    }

    @SubscribeEvent
    public void onPlayerChangedDimension(PlayerEvent.PlayerChangedDimensionEvent event) {
        // Re-sync bot visibility for the traveler: bots in the new dimension
        // spawn in, bots elsewhere are removed (the client would otherwise
        // keep phantom copies from the old world, or miss bots in the new).
        if (event.getEntity() instanceof net.minecraft.server.level.ServerPlayer traveler) {
            long sendAt = traveler.getServer().getTickCount() + SPAWN_PACKET_DELAY_TICKS;
            pendingSpawns.add(new PendingSpawn(traveler, sendAt));
        }
    }

    @SubscribeEvent
    public void onPlayerRespawn(PlayerEvent.PlayerRespawnEvent event) {
        if (event.getEntity() instanceof net.minecraft.server.level.ServerPlayer respawned) {
            long sendAt = respawned.getServer().getTickCount() + SPAWN_PACKET_DELAY_TICKS;
            pendingSpawns.add(new PendingSpawn(respawned, sendAt));
        }
    }

    @SubscribeEvent
    public void onRightClickItem(PlayerInteractEvent.RightClickItem event) {
        if (!(event.getEntity() instanceof net.minecraft.server.level.ServerPlayer clicker)) return;
        if (clicker.isShiftKeyDown()) {
            List<BotPlayer> visible = new ArrayList<>();
            for (var bot : BotManager.getAllBots().values()) {
                if (bot.isLookingAt(clicker, 5.0)) {
                    visible.add(bot);
                }
            }
            if (visible.size() == 1) {
                BotPlayer bot = visible.get(0);
                String botName = bot.getPlayer().getName().getString();
                int entityId = bot.getPlayer().getId();
                clicker.openMenu(new SimpleMenuProvider(
                        (id, inv, p) -> new BotEquipmentMenu(id, inv, bot.getPlayer().getInventory(), entityId),
                        Component.literal(botName + "'s Inventory")
                ), buf -> buf.writeInt(entityId));
                event.setCanceled(true);
            } else if (visible.size() > 1) {
                clicker.openMenu(new SimpleMenuProvider(
                        (id, inv, p) -> new BotSelectionMenu(id, inv, visible),
                        Component.literal("Select Bot (" + visible.size() + " nearby)")
                ));
                event.setCanceled(true);
            }
        }
    }

    @SubscribeEvent
    public void onServerChat(ServerChatEvent event) {
        String sender = event.getPlayer().getName().getString();
        String message = event.getRawText();
        for (var bot : BotManager.getAllBots().values()) {
            if (!sender.equals(bot.getPlayer().getName().getString())) {
                bot.addChatMessage(sender, message);
            }
        }
    }
}
