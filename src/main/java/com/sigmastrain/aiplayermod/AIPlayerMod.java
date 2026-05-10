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
        BotShop.init(event.getServer().getServerDirectory());
        TransmuteRegistry.init(event.getServer().getServerDirectory());
        EnchantmentRegistry.init(event.getServer());

        int port = Integer.parseInt(System.getProperty("aiplayermod.api.port",
                System.getenv().getOrDefault("AIPLAYER_API_PORT", String.valueOf(DEFAULT_API_PORT))));
        String apiKey = System.getProperty("aiplayermod.api.key",
                System.getenv().getOrDefault("AIPLAYER_API_KEY", ""));

        apiServer = new HttpApiServer(port, apiKey);
        apiServer.start();
        LOGGER.info("AI Player API server started on port {}", port);
    }

    @SubscribeEvent
    public void onServerStopping(ServerStoppingEvent event) {
        if (apiServer != null) {
            apiServer.stop();
        }
        TransmuteRegistry.saveConfig();
        BotManager.shutdown();
    }

    @SubscribeEvent
    public void onServerTick(ServerTickEvent.Post event) {
        BotManager.tick();
        TransmuteRegistry.tickSave(event.getServer().getTickCount());

        long currentTick = event.getServer().getTickCount();
        PendingSpawn pending;
        while ((pending = pendingSpawns.peek()) != null && currentTick >= pending.sendAtTick()) {
            pendingSpawns.poll();
            if (pending.joiner().isAlive() && pending.joiner().connection != null) {
                for (var bot : BotManager.getAllBots().values()) {
                    bot.sendSpawnPackets(pending.joiner());
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
