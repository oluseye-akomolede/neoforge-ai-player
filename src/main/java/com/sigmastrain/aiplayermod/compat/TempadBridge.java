package com.sigmastrain.aiplayermod.compat;

import com.mojang.authlib.GameProfile;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.level.Level;
import net.minecraft.world.phys.Vec3;
import net.neoforged.fml.ModList;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Writes waypoints into a player's TemPad.
 *
 * <p>Turns reconnaissance into transport: a bot finds a structure, the
 * coordinates land in your device, and you open a Timedoor to it. Without this
 * a located structure is a number in a log that somebody still has to walk to.
 *
 * <p>Reflection rather than a compile dependency, deliberately. Binding against
 * TemPad would drag in resourcefullib too, and the modpack is frozen — a hard
 * dependency on two jars we do not control is exactly the coupling that rule
 * exists to prevent. The surface is one constructor and one method, so the cost
 * of reflection is small and the failure mode is a logged no-op instead of a
 * mod that will not load.
 *
 * <p>What it calls, verified against tempad-1.21.1-3.0.4:
 * <pre>
 *   DefaultLocationHandler(GameProfile).plusAssign(NamedGlobalVec3)
 *   NamedGlobalVec3(Component, Vec3, ResourceKey&lt;Level&gt;, float, Color)
 * </pre>
 * {@code plusAssign} puts into {@code PlayerPointsData}, which is server saved
 * data keyed by player UUID — so writes work whether or not the player is
 * online, and survive restarts.
 */
public final class TempadBridge {

    private TempadBridge() {}

    private static final String TEMPAD_MOD_ID = "tempad";
    private static final String CLS_NAMED_VEC = "earth.terrarium.tempad.api.locations.NamedGlobalVec3";
    private static final String CLS_HANDLER =
            "earth.terrarium.tempad.common.location_handlers.DefaultLocationHandler";
    private static final String CLS_COLOR = "com.teamresourceful.resourcefullib.common.color.Color";

    /** Default waypoint tint — TemPad's own teal, so bot pins look native. */
    public static final int DEFAULT_COLOR = 0xFF55FFFF;

    private static Boolean available;
    private static Constructor<?> namedVecCtor;
    private static Constructor<?> colorCtor;
    private static Constructor<?> handlerCtor;
    private static Method plusAssign;
    private static Method getLocations;
    private static String initError;

    public static synchronized boolean isAvailable() {
        if (available != null) return available;
        if (!ModList.get().isLoaded(TEMPAD_MOD_ID)) {
            available = false;
            initError = "tempad is not loaded";
            return false;
        }
        try {
            Class<?> namedVec = Class.forName(CLS_NAMED_VEC);
            Class<?> color = Class.forName(CLS_COLOR);
            Class<?> handler = Class.forName(CLS_HANDLER);

            colorCtor = color.getConstructor(int.class);
            namedVecCtor = namedVec.getConstructor(
                    Component.class, Vec3.class, ResourceKey.class, float.class, color);
            handlerCtor = handler.getConstructor(GameProfile.class);
            plusAssign = handler.getMethod("plusAssign", namedVec);
            getLocations = handler.getMethod("getLocations");

            available = true;
            AIPlayerMod.LOGGER.info("TemPad bridge active — bots can write waypoints to player devices");
        } catch (Throwable t) {
            available = false;
            initError = t.getClass().getSimpleName() + ": " + t.getMessage();
            AIPlayerMod.LOGGER.warn("TemPad present but its API did not match expectations ({}), "
                    + "waypoint sharing disabled", initError);
        }
        return available;
    }

    public static String unavailableReason() {
        isAvailable();
        return initError == null ? "unknown" : initError;
    }

    /**
     * Add a waypoint to {@code owner}'s TemPad.
     *
     * @return null on success, or a human-readable reason it did not happen.
     */
    public static String addWaypoint(GameProfile owner, String name, Vec3 pos,
                                     ResourceKey<Level> dimension, int argbColor) {
        if (!isAvailable()) return "tempad unavailable (" + unavailableReason() + ")";
        if (owner == null) return "no player profile";
        try {
            Object color = colorCtor.newInstance(argbColor);
            Object waypoint = namedVecCtor.newInstance(
                    Component.literal(name), pos, dimension, 0.0f, color);
            Object handler = handlerCtor.newInstance(owner);
            plusAssign.invoke(handler, waypoint);
            AIPlayerMod.LOGGER.info("TemPad waypoint '{}' -> {} at {} {} {} in {}",
                    name, owner.getName(), (int) pos.x, (int) pos.y, (int) pos.z,
                    dimension.location());
            return null;
        } catch (Throwable t) {
            String msg = t.getClass().getSimpleName() + ": " + t.getMessage();
            AIPlayerMod.LOGGER.warn("TemPad waypoint write failed: {}", msg);
            return msg;
        }
    }

    /**
     * Remove a waypoint by id.
     *
     * <p>A device bots can write to needs a way to take things out of it —
     * otherwise a bad pin (or a stale one) is permanent from our side.
     *
     * @return null on success, or a reason it did not happen.
     */
    public static String removeWaypoint(GameProfile owner, UUID waypointId) {
        if (!isAvailable()) return "tempad unavailable (" + unavailableReason() + ")";
        if (owner == null || waypointId == null) return "missing player or waypoint id";
        try {
            Object handler = handlerCtor.newInstance(owner);
            Method minus = handler.getClass().getMethod("minusAssign", UUID.class);
            minus.invoke(handler, waypointId);
            AIPlayerMod.LOGGER.info("TemPad waypoint {} removed from {}", waypointId, owner.getName());
            return null;
        } catch (Throwable t) {
            String msg = t.getClass().getSimpleName() + ": " + t.getMessage();
            AIPlayerMod.LOGGER.warn("TemPad waypoint removal failed: {}", msg);
            return msg;
        }
    }

    /** Existing waypoints, for verification and the dashboard. */
    public static List<Map<String, Object>> listWaypoints(GameProfile owner) {
        if (!isAvailable() || owner == null) return List.of();
        try {
            Object handler = handlerCtor.newInstance(owner);
            Object raw = getLocations.invoke(handler);
            if (!(raw instanceof Map<?, ?> map)) return List.of();
            List<Map<String, Object>> out = new java.util.ArrayList<>();
            for (Map.Entry<?, ?> e : map.entrySet()) {
                Object v = e.getValue();
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("id", String.valueOf(e.getKey()));
                row.put("name", readString(v, "getName"));
                row.put("x", readInt(v, "getX"));
                row.put("y", readInt(v, "getY"));
                row.put("z", readInt(v, "getZ"));
                row.put("dimension", readDimension(v));
                out.add(row);
            }
            return out;
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("TemPad waypoint read failed: {}", t.toString());
            return List.of();
        }
    }

    private static String readString(Object o, String getter) {
        try {
            Object r = o.getClass().getMethod(getter).invoke(o);
            return r instanceof Component c ? c.getString() : String.valueOf(r);
        } catch (Throwable t) {
            return "?";
        }
    }

    private static int readInt(Object o, String getter) {
        try {
            return (int) o.getClass().getMethod(getter).invoke(o);
        } catch (Throwable t) {
            return 0;
        }
    }

    private static String readDimension(Object o) {
        try {
            Object key = o.getClass().getMethod("getDimension").invoke(o);
            if (key instanceof ResourceKey<?> rk) return rk.location().toString();
        } catch (Throwable ignored) {
        }
        return "";
    }

    // ── player resolution ────────────────────────────────────────────────

    /**
     * Profile for a player name — online first, then the server's profile
     * cache so a bot can leave a waypoint for someone who logged off.
     */
    public static GameProfile resolveProfile(MinecraftServer server, String playerName) {
        if (server == null || playerName == null || playerName.isBlank()) return null;
        var online = server.getPlayerList().getPlayerByName(playerName);
        if (online != null) return online.getGameProfile();
        try {
            Optional<GameProfile> cached = server.getProfileCache() == null
                    ? Optional.empty()
                    : server.getProfileCache().get(playerName);
            return cached.orElse(null);
        } catch (Throwable t) {
            return null;
        }
    }

    /** Human-friendly waypoint label from a structure id: "minecraft:end_city" → "End City". */
    public static String prettyName(String structureId) {
        String path = structureId == null ? "" : structureId;
        int colon = path.indexOf(':');
        if (colon >= 0) path = path.substring(colon + 1);
        path = path.replace('_', ' ').trim();
        if (path.isEmpty()) return "Waypoint";
        StringBuilder sb = new StringBuilder();
        for (String word : path.split("\\s+")) {
            if (word.isEmpty()) continue;
            sb.append(Character.toUpperCase(word.charAt(0))).append(word.substring(1)).append(' ');
        }
        return sb.toString().trim();
    }

    /** Stable-ish tint per structure family so pins are visually sortable. */
    public static int colorFor(String structureId) {
        if (structureId == null) return DEFAULT_COLOR;
        String s = structureId.toLowerCase();
        if (s.contains("end_city") || s.contains("end")) return 0xFFD9A6FF;   // end purple
        if (s.contains("fortress") || s.contains("bastion")) return 0xFFFF7043; // nether orange
        if (s.contains("village")) return 0xFF9CCC65;                          // green
        if (s.contains("monument") || s.contains("ocean") || s.contains("shipwreck")) return 0xFF4FC3F7;
        if (s.contains("mansion") || s.contains("stronghold")) return 0xFFFFD54F;
        return DEFAULT_COLOR;
    }

    /** UUID helper for callers that want to address a profile directly. */
    public static GameProfile profileFor(MinecraftServer server, UUID id) {
        if (server == null || id == null) return null;
        var online = server.getPlayerList().getPlayer(id);
        if (online != null) return online.getGameProfile();
        try {
            return server.getProfileCache() == null ? null
                    : server.getProfileCache().get(id).orElse(null);
        } catch (Throwable t) {
            return null;
        }
    }

    /** For logging / diagnostics. */
    public static ResourceLocation modId() {
        return ResourceLocation.fromNamespaceAndPath(TEMPAD_MOD_ID, "location");
    }
}
