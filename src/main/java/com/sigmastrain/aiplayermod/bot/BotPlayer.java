package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.actions.ActionQueue;
import com.mojang.authlib.GameProfile;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.network.CommonListenerCookie;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ClientInformation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.players.PlayerList;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
import net.minecraft.core.registries.BuiltInRegistries;

import java.util.*;

public class BotPlayer {
    private final ServerPlayer player;
    private final ActionQueue actionQueue;
    private boolean alive = true;

    private volatile Map<String, Object> cachedStatus = new LinkedHashMap<>();
    private volatile List<Map<String, Object>> cachedInventory = new ArrayList<>();
    private volatile List<Map<String, Object>> cachedEntities = new ArrayList<>();
    private volatile List<Map<String, Object>> cachedBlocks = new ArrayList<>();

    private BotPlayer(ServerPlayer player) {
        this.player = player;
        this.actionQueue = new ActionQueue(this);
    }

    public static BotPlayer create(MinecraftServer server, String name) {
        ServerLevel overworld = server.overworld();
        GameProfile profile = new GameProfile(UUID.nameUUIDFromBytes(("Bot:" + name).getBytes()), name);

        ServerPlayer botPlayer = new ServerPlayer(server, overworld, profile, ClientInformation.createDefault());
        botPlayer.moveTo(overworld.getSharedSpawnPos(), 0.0f, 0.0f);

        PlayerList playerList = server.getPlayerList();
        try {
            playerList.placeNewPlayer(
                    new BotConnection(server),
                    botPlayer,
                    CommonListenerCookie.createInitial(profile, false)
            );
        } catch (Exception e) {
            AIPlayerMod.LOGGER.warn("Non-fatal error during bot spawn (likely mod payload): {}", e.getMessage());
        }

        return new BotPlayer(botPlayer);
    }

    public void remove() {
        if (!alive) return;
        alive = false;
        actionQueue.clear();
        player.getServer().getPlayerList().remove(player);
    }

    public boolean isAlive() {
        return alive && !player.isRemoved();
    }

    public ServerPlayer getPlayer() {
        return player;
    }

    public ActionQueue getActionQueue() {
        return actionQueue;
    }

    public void tickActions() {
        if (!isAlive()) return;
        actionQueue.tick();
        refreshCache();
    }

    private void refreshCache() {
        cachedStatus = getStatus();
        cachedInventory = getInventory();
        cachedEntities = getNearbyEntities(24.0);
        cachedBlocks = getNearbyBlocks(8);
    }

    public Map<String, Object> getCachedStatus() { return cachedStatus; }
    public List<Map<String, Object>> getCachedInventory() { return cachedInventory; }
    public List<Map<String, Object>> getCachedEntities() { return cachedEntities; }
    public List<Map<String, Object>> getCachedBlocks() { return cachedBlocks; }

    // ── Chat ──

    public void chat(String message) {
        if (!isAlive()) return;
        player.getServer().getPlayerList().broadcastSystemMessage(
                Component.literal("<" + player.getName().getString() + "> " + message), false);
    }

    // ── Movement ──

    public void teleport(double x, double y, double z) {
        if (!isAlive()) return;
        player.teleportTo(player.serverLevel(), x, y, z, player.getYRot(), player.getXRot());
    }

    public void lookAt(double x, double y, double z) {
        if (!isAlive()) return;
        Vec3 pos = player.position();
        double dx = x - pos.x;
        double dy = y - (pos.y + player.getEyeHeight());
        double dz = z - pos.z;
        double dist = Math.sqrt(dx * dx + dz * dz);
        float yaw = (float) (Math.atan2(-dx, dz) * (180.0 / Math.PI));
        float pitch = (float) (Math.atan2(-dy, dist) * (180.0 / Math.PI));
        player.setYRot(yaw);
        player.setXRot(pitch);
    }

    // ── World observation ──

    public Map<String, Object> getStatus() {
        Map<String, Object> status = new LinkedHashMap<>();
        status.put("name", player.getName().getString());
        status.put("health", player.getHealth());
        status.put("food", player.getFoodData().getFoodLevel());
        status.put("saturation", player.getFoodData().getSaturationLevel());
        status.put("position", formatPos(player.position()));
        status.put("dimension", player.level().dimension().location().toString());
        status.put("gamemode", player.gameMode.getGameModeForPlayer().getName());
        status.put("alive", isAlive());
        return status;
    }

    public List<Map<String, Object>> getNearbyEntities(double radius) {
        List<Map<String, Object>> result = new ArrayList<>();
        AABB box = player.getBoundingBox().inflate(radius);
        for (Entity entity : player.level().getEntities(player, box)) {
            Map<String, Object> info = new LinkedHashMap<>();
            info.put("type", entity.getType().toShortString());
            info.put("name", entity.getName().getString());
            info.put("position", formatPos(entity.position()));
            info.put("distance", String.format("%.1f", entity.distanceTo(player)));
            if (entity instanceof LivingEntity le) {
                info.put("health", le.getHealth());
            }
            result.add(info);
        }
        return result;
    }

    public List<Map<String, Object>> getNearbyBlocks(int radius) {
        List<Map<String, Object>> result = new ArrayList<>();
        BlockPos center = player.blockPosition();
        Set<String> seen = new HashSet<>();
        for (int x = -radius; x <= radius; x++) {
            for (int y = -radius; y <= radius; y++) {
                for (int z = -radius; z <= radius; z++) {
                    BlockPos pos = center.offset(x, y, z);
                    BlockState state = player.level().getBlockState(pos);
                    if (!state.isAir()) {
                        String blockName = state.getBlock().getName().getString();
                        if (seen.add(blockName)) {
                            Map<String, Object> info = new LinkedHashMap<>();
                            info.put("block", blockName);
                            info.put("position", formatBlockPos(pos));
                            result.add(info);
                        }
                    }
                }
            }
        }
        return result;
    }

    public List<Map<String, Object>> getInventory() {
        List<Map<String, Object>> result = new ArrayList<>();
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty()) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("slot", i);
                item.put("item", stack.getItem().toString());
                item.put("count", stack.getCount());
                result.add(item);
            }
        }
        return result;
    }

    private Map<String, Double> formatPos(Vec3 pos) {
        Map<String, Double> map = new LinkedHashMap<>();
        map.put("x", Math.round(pos.x * 10.0) / 10.0);
        map.put("y", Math.round(pos.y * 10.0) / 10.0);
        map.put("z", Math.round(pos.z * 10.0) / 10.0);
        return map;
    }

    public List<Map<String, Object>> findBlocks(String blockName, int radius, int maxCount) {
        List<Map<String, Object>> result = new ArrayList<>();
        BlockPos center = player.blockPosition();
        String search = blockName.toLowerCase();
        for (int x = -radius; x <= radius && result.size() < maxCount; x++) {
            for (int y = -radius; y <= radius && result.size() < maxCount; y++) {
                for (int z = -radius; z <= radius && result.size() < maxCount; z++) {
                    BlockPos pos = center.offset(x, y, z);
                    BlockState state = player.level().getBlockState(pos);
                    if (!state.isAir()) {
                        String name = state.getBlock().getName().getString().toLowerCase();
                        String id = net.minecraft.core.registries.BuiltInRegistries.BLOCK
                                .getKey(state.getBlock()).toString();
                        if (name.contains(search) || id.contains(search)) {
                            Map<String, Object> info = new LinkedHashMap<>();
                            info.put("block", id);
                            info.put("name", name);
                            info.put("position", formatBlockPos(pos));
                            result.add(info);
                        }
                    }
                }
            }
        }
        return result;
    }

    public List<Map<String, Object>> findEntities(String entityName, double radius) {
        List<Map<String, Object>> result = new ArrayList<>();
        String search = entityName.toLowerCase();
        AABB box = player.getBoundingBox().inflate(radius);
        for (Entity entity : player.level().getEntities(player, box)) {
            String type = entity.getType().toShortString().toLowerCase();
            String name = entity.getName().getString().toLowerCase();
            if (type.contains(search) || name.contains(search)) {
                Map<String, Object> info = new LinkedHashMap<>();
                info.put("type", entity.getType().toShortString());
                info.put("name", entity.getName().getString());
                info.put("position", formatPos(entity.position()));
                info.put("distance", String.format("%.1f", entity.distanceTo(player)));
                if (entity instanceof LivingEntity le) {
                    info.put("health", le.getHealth());
                }
                result.add(info);
            }
        }
        return result;
    }

    public boolean swapSlot(int from, int to) {
        if (from < 0 || from >= player.getInventory().getContainerSize()) return false;
        if (to < 0 || to >= player.getInventory().getContainerSize()) return false;
        ItemStack a = player.getInventory().getItem(from);
        ItemStack b = player.getInventory().getItem(to);
        player.getInventory().setItem(from, b);
        player.getInventory().setItem(to, a);
        return true;
    }

    private Map<String, Integer> formatBlockPos(BlockPos pos) {
        Map<String, Integer> map = new LinkedHashMap<>();
        map.put("x", pos.getX());
        map.put("y", pos.getY());
        map.put("z", pos.getZ());
        return map;
    }
}
