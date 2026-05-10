package com.sigmastrain.aiplayermod.compat;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.server.level.ServerPlayer;
import net.neoforged.fml.ModList;

import java.lang.reflect.Method;
import java.util.UUID;

public class FtbCompat {
    private static boolean checked = false;
    private static boolean available = false;

    private static Method teamsApiMethod;
    private static Method teamsGetManagerMethod;
    private static Method playerLoggedInMethod;

    private static Method chunksApiMethod;
    private static Method chunksGetManagerMethod;
    private static Method getOrCreateDataMethod;

    public static void registerBotPlayer(ServerPlayer botPlayer) {
        if (!check()) return;

        String name = botPlayer.getName().getString();
        UUID uuid = botPlayer.getUUID();

        // Step 1: Register with FTB Teams (creates a PlayerTeam for the bot)
        if (teamsApiMethod != null && playerLoggedInMethod != null) {
            try {
                Object teamsApi = teamsApiMethod.invoke(null);
                Object teamsManager = teamsGetManagerMethod.invoke(teamsApi);
                if (teamsManager != null) {
                    playerLoggedInMethod.invoke(teamsManager, botPlayer, uuid, name);
                    AIPlayerMod.LOGGER.info("FTB Teams: registered bot {} ({})", name, uuid);
                }
            } catch (Exception e) {
                AIPlayerMod.LOGGER.debug("FTB Teams compat: could not register bot {} — {}", name, e.getMessage());
            }
        }

        // Step 2: Register with FTB Chunks (creates ChunkTeamData)
        if (chunksApiMethod != null && getOrCreateDataMethod != null) {
            try {
                Object chunksApi = chunksApiMethod.invoke(null);
                Object chunksManager = chunksGetManagerMethod.invoke(chunksApi);
                if (chunksManager != null) {
                    Object data = getOrCreateDataMethod.invoke(chunksManager, botPlayer);
                    if (data != null) {
                        AIPlayerMod.LOGGER.info("FTB Chunks: registered data for bot {}", name);
                    } else {
                        AIPlayerMod.LOGGER.warn("FTB Chunks: getOrCreateData returned null for bot {}", name);
                    }
                }
            } catch (Exception e) {
                AIPlayerMod.LOGGER.debug("FTB Chunks compat: could not register bot {} — {}", name, e.getMessage());
            }
        }
    }

    private static boolean check() {
        if (checked) return available;
        checked = true;

        boolean teamsOk = initTeams();
        boolean chunksOk = initChunks();
        available = teamsOk || chunksOk;

        if (available) {
            AIPlayerMod.LOGGER.info("FTB compat: teams={}, chunks={}", teamsOk, chunksOk);
        }
        return available;
    }

    private static boolean initTeams() {
        try {
            if (!ModList.get().isLoaded("ftbteams")) return false;

            Class<?> apiClass = Class.forName("dev.ftb.mods.ftbteams.api.FTBTeamsAPI");
            teamsApiMethod = apiClass.getMethod("api");
            Object api = teamsApiMethod.invoke(null);

            teamsGetManagerMethod = api.getClass().getMethod("getManager");
            Object manager = teamsGetManagerMethod.invoke(api);
            if (manager == null) return false;

            for (Method m : manager.getClass().getMethods()) {
                if (m.getName().equals("playerLoggedIn") && m.getParameterCount() == 3) {
                    playerLoggedInMethod = m;
                    break;
                }
            }
            return playerLoggedInMethod != null;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("FTB Teams compat: not available — {}", e.getMessage());
            return false;
        }
    }

    private static boolean initChunks() {
        try {
            if (!ModList.get().isLoaded("ftbchunks")) return false;

            Class<?> apiClass = Class.forName("dev.ftb.mods.ftbchunks.api.FTBChunksAPI");
            chunksApiMethod = apiClass.getMethod("api");
            Object api = chunksApiMethod.invoke(null);

            chunksGetManagerMethod = api.getClass().getMethod("getManager");
            Object manager = chunksGetManagerMethod.invoke(api);
            if (manager == null) return false;

            for (Method m : manager.getClass().getMethods()) {
                if (m.getName().equals("getOrCreateData") && m.getParameterCount() == 1
                        && m.getParameterTypes()[0].isAssignableFrom(ServerPlayer.class)) {
                    getOrCreateDataMethod = m;
                    break;
                }
            }

            if (getOrCreateDataMethod == null) {
                for (Class<?> iface : manager.getClass().getInterfaces()) {
                    for (Method m : iface.getMethods()) {
                        if (m.getName().equals("getOrCreateData") && m.getParameterCount() == 1
                                && m.getParameterTypes()[0].isAssignableFrom(ServerPlayer.class)) {
                            getOrCreateDataMethod = m;
                            break;
                        }
                    }
                    if (getOrCreateDataMethod != null) break;
                }
            }

            return getOrCreateDataMethod != null;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("FTB Chunks compat: not available — {}", e.getMessage());
            return false;
        }
    }
}
