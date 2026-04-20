package com.sigmastrain.aiplayermod;

import com.sigmastrain.aiplayermod.api.HttpApiServer;
import com.sigmastrain.aiplayermod.bot.BotManager;
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
import com.sigmastrain.aiplayermod.bot.BotInventoryMenu;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.network.chat.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Mod(AIPlayerMod.MOD_ID)
public class AIPlayerMod {
    public static final String MOD_ID = "aiplayermod";
    public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

    private static final int DEFAULT_API_PORT = 3100;

    private HttpApiServer apiServer;

    public AIPlayerMod(IEventBus modEventBus, ModContainer modContainer) {
        NeoForge.EVENT_BUS.register(this);
        LOGGER.info("AI Player Mod initializing");
    }

    @SubscribeEvent
    public void onServerStarted(ServerStartedEvent event) {
        BotManager.init(event.getServer());

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
        BotManager.shutdown();
    }

    @SubscribeEvent
    public void onServerTick(ServerTickEvent.Post event) {
        BotManager.tick();
    }

    @SubscribeEvent
    public void onRegisterCommands(RegisterCommandsEvent event) {
        ModCommands.register(event.getDispatcher());
    }

    @SubscribeEvent
    public void onPlayerLoggedIn(PlayerEvent.PlayerLoggedInEvent event) {
        if (event.getEntity() instanceof net.minecraft.server.level.ServerPlayer joiner) {
            for (var bot : BotManager.getAllBots().values()) {
                bot.sendSpawnPackets(joiner);
            }
        }
    }

    @SubscribeEvent
    public void onRightClickItem(PlayerInteractEvent.RightClickItem event) {
        if (!(event.getEntity() instanceof net.minecraft.server.level.ServerPlayer clicker)) return;
        if (clicker.isShiftKeyDown()) {
            for (var bot : BotManager.getAllBots().values()) {
                if (bot.isLookingAt(clicker, 5.0)) {
                    String botName = bot.getPlayer().getName().getString();
                    clicker.openMenu(new SimpleMenuProvider(
                            (id, inv, p) -> new BotInventoryMenu(id, inv, bot.getPlayer().getInventory()),
                            Component.literal(botName + "'s Inventory")
                    ));
                    event.setCanceled(true);
                    return;
                }
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
