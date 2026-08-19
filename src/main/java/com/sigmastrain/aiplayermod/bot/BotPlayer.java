package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.actions.ActionQueue;
import com.sigmastrain.aiplayermod.brain.BotBrain;
import com.sigmastrain.aiplayermod.shop.EnchantmentRegistry;
import com.sigmastrain.aiplayermod.shop.TransmuteRegistry;
import com.mojang.authlib.GameProfile;
import com.google.gson.*;
import net.minecraft.core.BlockPos;
import net.minecraft.core.HolderLookup;
import net.minecraft.ChatFormatting;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.TagParser;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.network.chat.Style;
import net.minecraft.network.protocol.game.*;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.network.CommonListenerCookie;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ClientInformation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.players.PlayerList;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;

import net.minecraft.world.SimpleContainer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.ai.attributes.Attributes;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.ConcurrentLinkedQueue;

public class BotPlayer {
    private final ServerPlayer player;
    private final ActionQueue actionQueue;
    private final BotBrain brain;
    private boolean alive = true;

    private final SimpleContainer extendedInventory = new SimpleContainer(54);
    /** Unbounded backing store — carried inventory is only the working set. */
    private final BotVault vault = new BotVault();
    private final ConcurrentLinkedQueue<Map<String, String>> chatInbox = new ConcurrentLinkedQueue<>();
    private static final int MAX_INBOX_SIZE = 50;

    private volatile Map<String, Object> cachedStatus = new LinkedHashMap<>();
    private volatile List<Map<String, Object>> cachedInventory = new ArrayList<>();
    private volatile List<Map<String, Object>> cachedEntities = new ArrayList<>();
    private volatile List<Map<String, Object>> cachedBlocks = new ArrayList<>();

    private double lastBroadcastX, lastBroadcastY, lastBroadcastZ;
    private float lastBroadcastYRot, lastBroadcastXRot;
    private int lastEquipmentHash;
    private int tickCounter;

    private BotPlayer(ServerPlayer player) {
        this.player = player;
        this.actionQueue = new ActionQueue(this);
        this.brain = new BotBrain(this);
    }

    public static BotPlayer create(MinecraftServer server, String name) {
        ServerLevel overworld = server.overworld();
        GameProfile profile = new GameProfile(UUID.nameUUIDFromBytes(("Bot:" + name).getBytes()), name);

        ServerPlayer botPlayer = new BotServerPlayer(server, overworld, profile, ClientInformation.createDefault());
        BlockPos spawn = overworld.getSharedSpawnPos();
        botPlayer.moveTo(spawn.getX() + 0.5, spawn.getY(), spawn.getZ() + 0.5, 0.0f, 0.0f);
        botPlayer.setOnGround(true);

        BotConnection connection = new BotConnection(server);
        CommonListenerCookie cookie = CommonListenerCookie.createInitial(profile, false);

        new BotPacketListener(server, connection, botPlayer, cookie);

        // Add bot to PlayerList.playersByUUID (but NOT the players list) so mods
        // like FTB Chunks can find the player via getPlayer(uuid) without the bot
        // appearing in getPlayers() iterations or triggering login events.
        addToPlayerLookup(server, botPlayer);

        BotPlayer bot = new BotPlayer(botPlayer);
        bot.broadcastSpawn();

        // Grant starting XP pool (10,000 points ≈ 53 levels)
        botPlayer.giveExperiencePoints(10000);

        server.execute(() -> {
            PmmoCompat.setupBotSkills(botPlayer);
            com.sigmastrain.aiplayermod.compat.FtbCompat.registerBotPlayer(botPlayer);
        });

        return bot;
    }

    // ── Packet-based visibility ──

    private void broadcastSpawn() {
        // Dimension-aware: a Minecraft client only models ITS dimension, so
        // spawn packets sent to a player in another one render a phantom
        // copy of the bot at the same raw coordinates in the wrong world
        // (live bug: Mystic in the End appeared to stand in the overworld,
        // and every order against the "overworld Mystic" looked like a
        // no-op). Players elsewhere get a remove instead — defensively, so
        // dimension CHANGES also clear any stale copy.
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) {
            if (online.level().dimension().equals(player.level().dimension())) {
                sendSpawnPackets(online);
                if (player.isPassenger() && player.getVehicle() != null) {
                    online.connection.send(new net.minecraft.network.protocol.game.ClientboundSetPassengersPacket(player.getVehicle()));
                }
            } else {
                online.connection.send(new ClientboundRemoveEntitiesPacket(player.getId()));
            }
        }
    }

    public void sendSpawnPackets(ServerPlayer target) {
        target.connection.send(new ClientboundPlayerInfoUpdatePacket(
                ClientboundPlayerInfoUpdatePacket.Action.ADD_PLAYER, player));
        target.connection.send(new ClientboundAddEntityPacket(
                player.getId(), player.getUUID(),
                player.getX(), player.getY(), player.getZ(),
                player.getXRot(), player.getYRot(),
                EntityType.PLAYER, 0, Vec3.ZERO, player.getYHeadRot()));
        List<SynchedEntityData.DataValue<?>> entityData = player.getEntityData().getNonDefaultValues();
        if (entityData != null && !entityData.isEmpty()) {
            target.connection.send(new ClientboundSetEntityDataPacket(player.getId(), entityData));
        }
        sendEquipmentPackets(target);
    }

    private void sendEquipmentPackets(ServerPlayer target) {
        List<com.mojang.datafixers.util.Pair<EquipmentSlot, ItemStack>> equipment = new ArrayList<>();
        for (EquipmentSlot slot : EquipmentSlot.values()) {
            ItemStack stack = getEquippedItem(slot);
            if (!stack.isEmpty()) {
                equipment.add(com.mojang.datafixers.util.Pair.of(slot, stack.copy()));
            }
        }
        if (!equipment.isEmpty()) {
            target.connection.send(new ClientboundSetEquipmentPacket(player.getId(), equipment));
        }
    }

    private ItemStack getEquippedItem(EquipmentSlot slot) {
        return switch (slot) {
            case HEAD -> player.getInventory().getItem(39);
            case CHEST -> player.getInventory().getItem(38);
            case LEGS -> player.getInventory().getItem(37);
            case FEET -> player.getInventory().getItem(36);
            case OFFHAND -> player.getInventory().getItem(40);
            case MAINHAND -> player.getInventory().getItem(player.getInventory().selected);
            default -> ItemStack.EMPTY;
        };
    }

    private void broadcastAllEquipment() {
        List<com.mojang.datafixers.util.Pair<EquipmentSlot, ItemStack>> equipment = new ArrayList<>();
        for (EquipmentSlot slot : EquipmentSlot.values()) {
            equipment.add(com.mojang.datafixers.util.Pair.of(slot, getEquippedItem(slot).copy()));
        }
        ClientboundSetEquipmentPacket packet = new ClientboundSetEquipmentPacket(player.getId(), equipment);
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) {
            online.connection.send(packet);
        }
    }

    public void broadcastEquipmentChange(EquipmentSlot slot, ItemStack stack) {
        ClientboundSetEquipmentPacket packet = new ClientboundSetEquipmentPacket(
                player.getId(),
                List.of(com.mojang.datafixers.util.Pair.of(slot, stack.copy()))
        );
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) {
            online.connection.send(packet);
        }
    }

    private boolean hasMoved() {
        return Math.abs(player.getX() - lastBroadcastX) > 0.01
                || Math.abs(player.getY() - lastBroadcastY) > 0.01
                || Math.abs(player.getZ() - lastBroadcastZ) > 0.01
                || Math.abs(player.getYRot() - lastBroadcastYRot) > 0.5f
                || Math.abs(player.getXRot() - lastBroadcastXRot) > 0.5f;
    }

    private int computeEquipmentHash() {
        int hash = 0;
        for (EquipmentSlot slot : EquipmentSlot.values()) {
            ItemStack stack = getEquippedItem(slot);
            hash = 31 * hash + ItemStack.hashItemAndComponents(stack);
        }
        return hash;
    }

    private void broadcastPosition() {
        // A riding bot is positioned by its vehicle on every client; a teleport
        // packet would fight that (and break SW's hide-passenger check). Send
        // only head rotation, and keep the client's rider→vehicle link fresh.
        boolean riding = player.isPassenger() && player.getVehicle() != null;
        ClientboundTeleportEntityPacket teleport = riding ? null : new ClientboundTeleportEntityPacket(player);
        ClientboundRotateHeadPacket head = new ClientboundRotateHeadPacket(player,
                (byte) ((int) (player.getYHeadRot() * 256.0f / 360.0f)));
        net.minecraft.network.protocol.game.ClientboundSetPassengersPacket riders =
                riding ? new net.minecraft.network.protocol.game.ClientboundSetPassengersPacket(player.getVehicle()) : null;
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) {
            if (teleport != null) online.connection.send(teleport);
            online.connection.send(head);
            if (riders != null && tickCounter % 20 == 0) online.connection.send(riders);
        }
    }

    /** Tell every client which vehicle this bot rides (after a (re)spawn packet the client forgets). */
    public void broadcastRiding() {
        if (!player.isPassenger() || player.getVehicle() == null) return;
        var pkt = new net.minecraft.network.protocol.game.ClientboundSetPassengersPacket(player.getVehicle());
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) online.connection.send(pkt);
    }

    public void remove() {
        if (!alive) return;
        alive = false;
        actionQueue.clear();
        removeFromPlayerLookup(player.getServer(), player);
        PlayerList playerList = player.getServer().getPlayerList();
        playerList.broadcastAll(new ClientboundRemoveEntitiesPacket(player.getId()));
        playerList.broadcastAll(new ClientboundPlayerInfoRemovePacket(List.of(player.getUUID())));
    }

    @SuppressWarnings("unchecked")
    private static void addToPlayerLookup(MinecraftServer server, ServerPlayer botPlayer) {
        try {
            PlayerList pl = server.getPlayerList();
            java.lang.reflect.Field field = PlayerList.class.getDeclaredField("playersByUUID");
            field.setAccessible(true);
            Map<UUID, ServerPlayer> map = (Map<UUID, ServerPlayer>) field.get(pl);
            map.put(botPlayer.getUUID(), botPlayer);
            AIPlayerMod.LOGGER.info("Added bot {} to PlayerList.playersByUUID", botPlayer.getName().getString());
        } catch (Exception e) {
            AIPlayerMod.LOGGER.warn("Could not add bot to PlayerList.playersByUUID: {}", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private static void removeFromPlayerLookup(MinecraftServer server, ServerPlayer botPlayer) {
        try {
            PlayerList pl = server.getPlayerList();
            java.lang.reflect.Field field = PlayerList.class.getDeclaredField("playersByUUID");
            field.setAccessible(true);
            Map<UUID, ServerPlayer> map = (Map<UUID, ServerPlayer>) field.get(pl);
            map.remove(botPlayer.getUUID());
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("Could not remove bot from PlayerList.playersByUUID: {}", e.getMessage());
        }
    }

    // ── Persistence ──

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    public void saveState(Path dir) {
        try {
            Files.createDirectories(dir);
            String name = player.getName().getString();
            HolderLookup.Provider registries = player.getServer().registryAccess();

            JsonObject root = new JsonObject();
            root.addProperty("name", name);
            root.addProperty("uuid", player.getUUID().toString());

            String dimension = player.serverLevel().dimension().location().toString();
            root.addProperty("dimension", dimension);
            root.addProperty("x", player.getX());
            root.addProperty("y", player.getY());
            root.addProperty("z", player.getZ());
            root.addProperty("yRot", player.getYRot());
            root.addProperty("xRot", player.getXRot());
            root.addProperty("xp", player.totalExperience);
            root.addProperty("health", player.getHealth());
            root.addProperty("anchored", AnchorManager.isAnchored(name));

            JsonArray inventory = new JsonArray();
            for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
                ItemStack stack = player.getInventory().getItem(i);
                if (stack.isEmpty()) continue;
                CompoundTag tag = (CompoundTag) stack.save(registries);
                JsonObject entry = new JsonObject();
                entry.addProperty("slot", i);
                entry.addProperty("nbt", tag.toString());
                inventory.add(entry);
            }
            root.add("inventory", inventory);

            JsonArray extended = new JsonArray();
            for (int i = 0; i < extendedInventory.getContainerSize(); i++) {
                ItemStack stack = extendedInventory.getItem(i);
                if (stack.isEmpty()) continue;
                CompoundTag tag = (CompoundTag) stack.save(registries);
                JsonObject entry = new JsonObject();
                entry.addProperty("slot", i);
                entry.addProperty("nbt", tag.toString());
                extended.add(entry);
            }
            root.add("extendedInventory", extended);

            // Worn curios — a restart once stripped every bot's wireless
            // terminal because this section didn't exist.
            JsonArray curiosArr = new JsonArray();
            for (var w : com.sigmastrain.aiplayermod.compat.curios.CuriosCompat.list(player)) {
                if (w.stack().isEmpty()) continue;
                CompoundTag tag = (CompoundTag) w.stack().save(registries);
                JsonObject entry = new JsonObject();
                entry.addProperty("slotType", w.slotType());
                entry.addProperty("index", w.index());
                entry.addProperty("nbt", tag.toString());
                curiosArr.add(entry);
            }
            root.add("curios", curiosArr);

            JsonArray vaultArr = new JsonArray();
            for (CompoundTag tag : vault.save(registries)) {
                JsonObject entry = new JsonObject();
                entry.addProperty("nbt", tag.toString());
                vaultArr.add(entry);
            }
            root.add("vault", vaultArr);

            Path file = dir.resolve(name + ".json");
            try (Writer w = Files.newBufferedWriter(file)) {
                GSON.toJson(root, w);
            }
            AIPlayerMod.LOGGER.info("Saved bot state: {} ({} items)", name, inventory.size() + extended.size());
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Failed to save bot state for {}", player.getName().getString(), e);
        }
    }

    public void loadState(Path dir) {
        String name = player.getName().getString();
        Path file = dir.resolve(name + ".json");
        if (!Files.exists(file)) return;

        try (Reader r = Files.newBufferedReader(file)) {
            JsonObject root = JsonParser.parseReader(r).getAsJsonObject();
            HolderLookup.Provider registries = player.getServer().registryAccess();

            // A bot must never respawn in a non-overworld dimension. A prior
            // session can send one to the End/Nether (an ender-pearl run), and
            // saveState faithfully records that dimension; restoring it strands
            // the bot in the_end/the_nether on spawn (live bug: Mystic came back
            // in the Nether, Axiom/Forge/Scout/Tiller in the End). Only an
            // overworld save is restored; a cross-dimension save falls back to
            // the overworld spawn that create() already placed us at.
            String dimStr = root.has("dimension")
                    ? root.get("dimension").getAsString() : "minecraft:overworld";
            if ("minecraft:overworld".equals(dimStr)) {
                ResourceKey<Level> dimKey = ResourceKey.create(Registries.DIMENSION, ResourceLocation.parse(dimStr));
                ServerLevel targetLevel = player.getServer().getLevel(dimKey);
                if (targetLevel != null) {
                    try {
                        var levelField = net.minecraft.world.entity.Entity.class.getDeclaredField("level");
                        levelField.setAccessible(true);
                        levelField.set(player, targetLevel);
                    } catch (Exception e) {
                        AIPlayerMod.LOGGER.warn("Failed to set bot dimension on load", e);
                    }
                }

                double x = root.get("x").getAsDouble();
                double y = root.get("y").getAsDouble();
                double z = root.get("z").getAsDouble();
                float yRot = root.has("yRot") ? root.get("yRot").getAsFloat() : 0;
                float xRot = root.has("xRot") ? root.get("xRot").getAsFloat() : 0;
                player.moveTo(x, y, z, yRot, xRot);
            } else {
                AIPlayerMod.LOGGER.warn("Bot {} saved in {} — respawning at overworld spawn instead",
                        name, dimStr);
            }

            if (root.has("xp")) {
                player.giveExperiencePoints(root.get("xp").getAsInt() - player.totalExperience);
            }
            if (root.has("health")) {
                player.setHealth(root.get("health").getAsFloat());
            }
            if (root.has("anchored") && root.get("anchored").getAsBoolean()) {
                // A fleet that believed it was anchored must not silently
                // freeze across a restart.
                String err = AnchorManager.enable(this);
                if (err != null) {
                    AIPlayerMod.LOGGER.warn("[anchor] {} could not re-anchor on load: {}",
                            name, err);
                }
            }

            player.getInventory().clearContent();
            if (root.has("inventory")) {
                for (JsonElement el : root.getAsJsonArray("inventory")) {
                    JsonObject entry = el.getAsJsonObject();
                    int slot = entry.get("slot").getAsInt();
                    CompoundTag tag = TagParser.parseTag(entry.get("nbt").getAsString());
                    ItemStack stack = ItemStack.parse(registries, tag).orElse(ItemStack.EMPTY);
                    if (!stack.isEmpty()) {
                        player.getInventory().setItem(slot, stack);
                    }
                }
            }

            if (root.has("extendedInventory")) {
                extendedInventory.clearContent();
                for (JsonElement el : root.getAsJsonArray("extendedInventory")) {
                    JsonObject entry = el.getAsJsonObject();
                    int slot = entry.get("slot").getAsInt();
                    CompoundTag tag = TagParser.parseTag(entry.get("nbt").getAsString());
                    ItemStack stack = ItemStack.parse(registries, tag).orElse(ItemStack.EMPTY);
                    if (!stack.isEmpty()) {
                        extendedInventory.setItem(slot, stack);
                    }
                }
            }

            if (root.has("curios")) {
                for (JsonElement el : root.getAsJsonArray("curios")) {
                    JsonObject entry = el.getAsJsonObject();
                    CompoundTag tag = TagParser.parseTag(entry.get("nbt").getAsString());
                    ItemStack stack = ItemStack.parse(registries, tag).orElse(ItemStack.EMPTY);
                    if (!stack.isEmpty()) {
                        boolean ok = com.sigmastrain.aiplayermod.compat.curios.CuriosCompat
                                .putDirect(player, entry.get("slotType").getAsString(),
                                        entry.get("index").getAsInt(), stack);
                        if (!ok) {
                            // Slot layout changed? Never destroy the item.
                            if (!player.getInventory().add(stack)) {
                                vault.deposit(stack);
                            }
                        }
                    }
                }
            }

            if (root.has("vault")) {
                List<ItemStack> loaded = new ArrayList<>();
                for (JsonElement el : root.getAsJsonArray("vault")) {
                    JsonObject entry = el.getAsJsonObject();
                    CompoundTag tag = TagParser.parseTag(entry.get("nbt").getAsString());
                    ItemStack stack = ItemStack.parse(registries, tag).orElse(ItemStack.EMPTY);
                    if (!stack.isEmpty()) loaded.add(stack);
                }
                vault.load(loaded);
                if (!loaded.isEmpty()) {
                    AIPlayerMod.LOGGER.info("Restored vault for {}: {} stacks", name, loaded.size());
                }
            }

            AIPlayerMod.LOGGER.info("Loaded bot state: {} at ({}, {}, {}) in {}", name,
                    (int) player.getX(), (int) player.getY(), (int) player.getZ(),
                    player.level().dimension().location());
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Failed to load bot state for {}", name, e);
        }
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

    public BotBrain getBrain() {
        return brain;
    }

    public void tickActions() {
        if (!isAlive()) return;
        try {
            brain.tick();
            if (!brain.hasActiveDirective()) {
                actionQueue.tick();
            }
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Action error for bot {}: {} ({})", player.getName().getString(), e.getMessage(), e.getClass().getSimpleName(), e);
        }
        scanInventoryForTransmutables();
        tickCounter++;
        boolean moved = hasMoved();
        if (moved || tickCounter % 20 == 0) {
            broadcastPosition();
            lastBroadcastX = player.getX();
            lastBroadcastY = player.getY();
            lastBroadcastZ = player.getZ();
            lastBroadcastYRot = player.getYRot();
            lastBroadcastXRot = player.getXRot();
        }
        int eqHash = computeEquipmentHash();
        if (eqHash != lastEquipmentHash) {
            broadcastAllEquipment();
            lastEquipmentHash = eqHash;
        }
        if (tickCounter % 40 == 0) {
            refreshCache();
        }
        if (tickCounter % 200 == 0) {
            broadcastSpawn();
        }
    }

    // ── Dimension travel ──

    /**
     * Standable Y at (x,z). In ceiling dimensions (the nether) the MOTION_BLOCKING
     * heightmap returns the top of the bedrock roof — a mob-free void that stranded
     * the entire war party in test round 2. Scan downward from below the ceiling
     * for a 2-block air pocket over solid, non-lava ground instead.
     */
    public static int safeGroundY(ServerLevel level, int x, int z, int preferredY) {
        if (!level.dimensionType().hasCeiling()) {
            return level.getHeight(net.minecraft.world.level.levelgen.Heightmap.Types.MOTION_BLOCKING, x, z);
        }
        int ceiling = level.getMinBuildHeight() + level.getLogicalHeight();
        int start = Math.min(preferredY > 0 ? preferredY : ceiling - 8, ceiling - 8);
        BlockPos.MutableBlockPos pos = new BlockPos.MutableBlockPos(x, start, z);
        int airRun = 0;
        for (int y = start; y > level.getMinBuildHeight() + 4; y--) {
            pos.setY(y);
            var state = level.getBlockState(pos);
            if (state.isAir()) {
                airRun++;
                continue;
            }
            if (airRun >= 2 && state.isSolid() && level.getFluidState(pos).isEmpty()) {
                return y + 1;
            }
            airRun = 0;
        }
        // No pocket found (unloaded / solid column) — mid-height beats the roof.
        return Math.max(level.getMinBuildHeight() + 32, 32);
    }

    public boolean teleportToDimension(ResourceKey<Level> dimension, double x, double y, double z) {
        if (!isAlive()) return false;
        MinecraftServer server = player.getServer();
        ServerLevel targetLevel = server.getLevel(dimension);
        if (targetLevel == null) return false;

        targetLevel.getChunkSource().getChunk((int) x >> 4, (int) z >> 4, true);
        y = safeGroundY(targetLevel, (int) x, (int) z, (int) y);

        remove();

        player.moveTo(x, y, z, player.getYRot(), player.getXRot());
        try {
            var levelField = net.minecraft.world.entity.Entity.class.getDeclaredField("level");
            levelField.setAccessible(true);
            levelField.set(player, targetLevel);
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Failed to set bot dimension", e);
            return false;
        }

        alive = true;
        broadcastSpawn();
        return true;
    }

    /** Exact block lookup for criteria verification (must run on server thread). */
    public Map<String, Object> blockAt(int x, int y, int z) {
        BlockPos pos = new BlockPos(x, y, z);
        var state = player.level().getBlockState(pos);
        String id = net.minecraft.core.registries.BuiltInRegistries.BLOCK
                .getKey(state.getBlock()).toString();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("block", id);
        out.put("x", x);
        out.put("y", y);
        out.put("z", z);
        return out;
    }

    private void refreshCache() {
        cachedStatus = getStatus();
        cachedInventory = getInventory();
        cachedEntities = getNearbyEntities(16.0);
        cachedBlocks = getNearbyBlocks(5);
    }

    public Map<String, Object> getCachedStatus() { return cachedStatus; }
    public List<Map<String, Object>> getCachedInventory() { return cachedInventory; }
    public List<Map<String, Object>> getCachedEntities() { return cachedEntities; }
    public List<Map<String, Object>> getCachedBlocks() { return cachedBlocks; }

    public void addChatMessage(String sender, String message) {
        // A named human giving this bot an order becomes its master (used to
        // resolve "follow me" and to shield the master from friendly fire).
        BotOwners.setMaster(player.getGameProfile().getName(), sender);
        Map<String, String> entry = new LinkedHashMap<>();
        entry.put("sender", sender);
        entry.put("message", message);
        chatInbox.add(entry);
        while (chatInbox.size() > MAX_INBOX_SIZE) {
            chatInbox.poll();
        }
    }

    public boolean hasPendingChat() {
        return !chatInbox.isEmpty();
    }

    public List<Map<String, String>> drainChatInbox() {
        List<Map<String, String>> messages = new ArrayList<>();
        Map<String, String> msg;
        while ((msg = chatInbox.poll()) != null) {
            messages.add(msg);
        }
        return messages;
    }

    // ── Chat ──

    public void chat(String message) {
        if (!isAlive()) return;
        player.getServer().getPlayerList().broadcastSystemMessage(
                Component.literal("<" + player.getName().getString() + "> " + message), false);
    }

    public void systemChat(String message, String color) {
        if (!isAlive()) return;
        ChatFormatting fmt = switch (color.toLowerCase()) {
            case "gold" -> ChatFormatting.GOLD;
            case "aqua" -> ChatFormatting.AQUA;
            case "green" -> ChatFormatting.GREEN;
            case "red" -> ChatFormatting.RED;
            case "yellow" -> ChatFormatting.YELLOW;
            case "light_purple" -> ChatFormatting.LIGHT_PURPLE;
            case "gray" -> ChatFormatting.GRAY;
            case "dark_aqua" -> ChatFormatting.DARK_AQUA;
            case "dark_green" -> ChatFormatting.DARK_GREEN;
            case "dark_purple" -> ChatFormatting.DARK_PURPLE;
            default -> ChatFormatting.GRAY;
        };
        MutableComponent prefix = Component.literal("[" + player.getName().getString() + "] ")
                .withStyle(Style.EMPTY.withColor(fmt).withBold(true));
        MutableComponent body = Component.literal(message)
                .withStyle(Style.EMPTY.withColor(fmt));
        player.getServer().getPlayerList().broadcastSystemMessage(
                prefix.append(body), false);
    }

    // ── Movement ──

    public void teleport(double x, double y, double z) {
        if (!isAlive()) return;
        player.moveTo(x, y, z, player.getYRot(), player.getXRot());
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
        player.setYHeadRot(yaw);
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
        status.put("anchored", AnchorManager.isAnchored(
                player.getGameProfile().getName()));
        status.put("xp_level", player.experienceLevel);
        status.put("xp_points", player.totalExperience);
        // Lifetime combat stats — lets L2 verify "killed N enemies" criteria
        // deterministically (delta vs a plan-start baseline) instead of a lax
        // LLM judgment. Vanilla stat counters accrue through the normal
        // kill-attribution path, which bot melee/ranged attacks use.
        try {
            status.put("mob_kills", player.getStats().getValue(
                    net.minecraft.stats.Stats.CUSTOM.get(net.minecraft.stats.Stats.MOB_KILLS)));
            status.put("deaths", player.getStats().getValue(
                    net.minecraft.stats.Stats.CUSTOM.get(net.minecraft.stats.Stats.DEATHS)));
        } catch (Exception e) {
            status.put("mob_kills", -1);
            status.put("deaths", -1);
        }
        Map<String, Object> vehicle = getVehicleInfo();
        if (vehicle != null) status.put("vehicle", vehicle);
        Map<String, Object> fusion = getFusionInfo();
        if (fusion != null) status.put("fusion", fusion);
        return status;
    }

    /**
     * The Superb Warfare vehicle this bot is aboard, or null. Keys: id, name,
     * type, seat, driver, energy, max_energy, health, max_health, weapon,
     * weapons, ammo, ammo_item, container_size, drivable.
     */
    public Map<String, Object> getVehicleInfo() {
        net.minecraft.world.entity.Entity v =
                SwVehicleCompat.vehicleOf(player);
        if (v == null) return null;
        Map<String, Object> m = new LinkedHashMap<>();
        int seat = SwVehicleCompat.seatIndex(v, player);
        m.put("id", v.getUUID().toString());
        m.put("name", SwVehicleCompat.displayName(v));
        m.put("type", SwVehicleCompat.typeName(v));
        m.put("seat", seat);
        m.put("driver", SwVehicleCompat.isDriver(player));
        m.put("energy", SwVehicleCompat.energy(v));
        m.put("max_energy", SwVehicleCompat.maxEnergy(v));
        m.put("health", SwVehicleCompat.health(v));
        m.put("max_health", SwVehicleCompat.maxHealth(v));
        boolean armed = SwVehicleCompat.hasWeapon(v, seat);
        m.put("weapon", armed ? SwVehicleCompat.weaponName(v, seat) : "");
        m.put("weapons", SwVehicleCompat.weaponNames(v, seat));
        m.put("ammo", armed ? SwVehicleCompat.ammoCount(player) : 0);
        m.put("ammo_item", SwVehicleCompat.ammoItemFor(player));
        m.put("container_size", SwVehicleCompat.containerSize(v));
        m.put("drivable", SwVehicleCompat.drivable(v));
        m.put("engine", SwVehicleCompat.engineKind(v).name());
        m.put("position", formatPos(v.position()));
        return m;
    }

    /** The block the bot is currently aimed at (its yaw/pitch), within reach, or null. */
    public net.minecraft.core.BlockPos blockLookingAt() {
        double reach = 6.0;
        net.minecraft.world.phys.Vec3 eye = player.getEyePosition();
        net.minecraft.world.phys.Vec3 look = player.getViewVector(1.0f);
        net.minecraft.world.phys.Vec3 end = eye.add(look.x * reach, look.y * reach, look.z * reach);
        net.minecraft.world.level.ClipContext ctx = new net.minecraft.world.level.ClipContext(
                eye, end, net.minecraft.world.level.ClipContext.Block.OUTLINE,
                net.minecraft.world.level.ClipContext.Fluid.NONE, player);
        net.minecraft.world.phys.BlockHitResult hit = player.level().clip(ctx);
        return hit.getType() == net.minecraft.world.phys.HitResult.Type.BLOCK ? hit.getBlockPos() : null;
    }

    /** Snapshot of the block this bot is fused with, or null. Includes a reactor readout when applicable. */
    public Map<String, Object> getFusionInfo() {
        var st = com.sigmastrain.aiplayermod.brain.Fusion.of(player.getGameProfile().getName());
        if (st == null) return null;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("dimension", st.dimension());
        m.put("x", st.pos().getX());
        m.put("y", st.pos().getY());
        m.put("z", st.pos().getZ());
        m.put("role", st.role().name());
        m.put("mode", st.mode().name());
        if (player.level() instanceof ServerLevel sl && sl.dimension().location().toString().equals(st.dimension())) {
            m.put("block", com.sigmastrain.aiplayermod.compat.blockfusion.BlockFusionCompat.blockName(sl, st.pos()));
            m.put("energy", com.sigmastrain.aiplayermod.compat.blockfusion.BlockFusionCompat.longStored(sl, st.pos()));
            m.put("max_energy", com.sigmastrain.aiplayermod.compat.blockfusion.BlockFusionCompat.longMaxEnergy(sl, st.pos()));
            var reg = com.sigmastrain.aiplayermod.compat.blockfusion.RegulatorRegistry.regulatorFor(sl, st.pos());
            if (reg != null) {
                var be = sl.getBlockEntity(st.pos());
                if (be != null) m.put("reactor", reg.read(be).toMap());
            }
        }
        m.put("knobs", com.sigmastrain.aiplayermod.brain.FusionControl.toMap(player.getGameProfile().getName()));
        return m;
    }

    /** Make the bot (in)visible while fused, so it reads as "merged" with the block. */
    public void setFusedInvisible(boolean invisible) {
        player.setInvisible(invisible);
        broadcastEntityData();
    }

    private void broadcastEntityData() {
        var data = player.getEntityData().getNonDefaultValues();
        if (data == null) return;
        var pkt = new net.minecraft.network.protocol.game.ClientboundSetEntityDataPacket(player.getId(), data);
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) online.connection.send(pkt);
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

    public List<Map<String, Object>> surfaceScan(int radius) {
        List<Map<String, Object>> result = new ArrayList<>();
        BlockPos center = player.blockPosition();
        Level level = player.level();
        int cy = center.getY();

        for (int dx = -radius; dx <= radius; dx++) {
            for (int dz = -radius; dz <= radius; dz++) {
                int wx = center.getX() + dx;
                int wz = center.getZ() + dz;
                // Scan downward from bot Y+10, find first non-air
                BlockPos.MutableBlockPos probe = new BlockPos.MutableBlockPos(wx, Math.min(cy + 10, level.getMaxBuildHeight()), wz);
                BlockState state = null;
                int surfaceY = cy;
                for (int y = probe.getY(); y >= Math.max(cy - 20, level.getMinBuildHeight()); y--) {
                    probe.setY(y);
                    BlockState bs = level.getBlockState(probe);
                    if (!bs.isAir() && !bs.getBlock().defaultBlockState().canBeReplaced()) {
                        state = bs;
                        surfaceY = y;
                        break;
                    }
                }
                if (state != null) {
                    String blockId = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
                    Map<String, Object> entry = new LinkedHashMap<>();
                    entry.put("x", wx);
                    entry.put("y", surfaceY);
                    entry.put("z", wz);
                    entry.put("block", blockId);
                    result.add(entry);
                }
            }
        }
        return result;
    }

    public List<Map<String, Object>> nearbyContainers(int radius) {
        List<Map<String, Object>> result = new ArrayList<>();
        BlockPos center = player.blockPosition();
        Level level = player.level();
        for (int dx = -radius; dx <= radius; dx++) {
            for (int dy = -radius; dy <= radius; dy++) {
                for (int dz = -radius; dz <= radius; dz++) {
                    BlockPos pos = center.offset(dx, dy, dz);
                    BlockState state = level.getBlockState(pos);
                    String blockId = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
                    if (blockId.contains("chest") || blockId.contains("barrel")
                            || blockId.contains("shulker_box")) {
                        Map<String, Object> entry = new LinkedHashMap<>();
                        entry.put("x", pos.getX());
                        entry.put("y", pos.getY());
                        entry.put("z", pos.getZ());
                        entry.put("block", blockId);
                        result.add(entry);
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
                result.add(serializeItemStack(stack, i));
            }
        }
        return result;
    }

    private Map<String, Object> serializeItemStack(ItemStack stack, int slot) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("slot", slot);
        item.put("item", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
        item.put("count", stack.getCount());
        item.put("display_name", stack.getHoverName().getString());
        item.put("max_stack_size", stack.getMaxStackSize());

        if (stack.isDamageableItem()) {
            item.put("durability", stack.getMaxDamage() - stack.getDamageValue());
            item.put("max_durability", stack.getMaxDamage());
        }

        var enchantments = stack.getEnchantments();
        if (!enchantments.isEmpty()) {
            List<Map<String, Object>> enchList = new ArrayList<>();
            enchantments.entrySet().forEach(entry -> {
                Map<String, Object> e = new LinkedHashMap<>();
                entry.getKey().unwrapKey().ifPresent(key ->
                    e.put("id", key.location().toString())
                );
                e.put("level", entry.getIntValue());
                if (!e.isEmpty()) enchList.add(e);
            });
            item.put("enchantments", enchList);
        }

        var attrs = stack.getAttributeModifiers();
        if (attrs != null && !attrs.modifiers().isEmpty()) {
            Map<String, Object> attributes = new LinkedHashMap<>();
            for (var entry : attrs.modifiers()) {
                String attrName = entry.attribute().unwrapKey()
                        .map(k -> k.location().getPath())
                        .orElse("unknown");
                double amount = entry.modifier().amount();
                String op = entry.modifier().operation().name().toLowerCase();
                String slotGroup = entry.slot().getSerializedName();
                attributes.put(attrName, Map.of(
                        "amount", Math.round(amount * 100.0) / 100.0,
                        "operation", op,
                        "slot", slotGroup
                ));
            }
            item.put("attributes", attributes);
        }

        return item;
    }

    // ── Container interaction ──

    public List<Map<String, Object>> readContainer(int x, int y, int z) {
        List<Map<String, Object>> result = new ArrayList<>();
        BlockPos pos = new BlockPos(x, y, z);
        var blockEntity = player.level().getBlockEntity(pos);
        if (blockEntity instanceof net.minecraft.world.Container container) {
            for (int i = 0; i < container.getContainerSize(); i++) {
                ItemStack stack = container.getItem(i);
                if (!stack.isEmpty()) {
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("slot", i);
                    item.put("item", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
                    item.put("name", stack.getHoverName().getString());
                    item.put("count", stack.getCount());
                    result.add(item);
                }
            }
        }
        return result;
    }

    public Map<String, Object> insertIntoContainer(int x, int y, int z, int invSlot, int count) {
        Map<String, Object> result = new LinkedHashMap<>();
        BlockPos pos = new BlockPos(x, y, z);
        var blockEntity = player.level().getBlockEntity(pos);
        if (!(blockEntity instanceof net.minecraft.world.Container container)) {
            result.put("error", "No container at position");
            return result;
        }
        ItemStack source = player.getInventory().getItem(invSlot);
        if (source.isEmpty()) {
            result.put("error", "Empty inventory slot");
            return result;
        }
        int toInsert = Math.min(count, source.getCount());
        ItemStack toPlace = source.copy();
        toPlace.setCount(toInsert);

        for (int i = 0; i < container.getContainerSize(); i++) {
            ItemStack existing = container.getItem(i);
            if (existing.isEmpty()) {
                container.setItem(i, toPlace);
                source.shrink(toInsert);
                container.setChanged();
                result.put("status", "inserted");
                result.put("count", toInsert);
                return result;
            } else if (ItemStack.isSameItemSameComponents(existing, toPlace)
                    && existing.getCount() + toInsert <= existing.getMaxStackSize()) {
                existing.grow(toInsert);
                source.shrink(toInsert);
                container.setChanged();
                result.put("status", "inserted");
                result.put("count", toInsert);
                return result;
            }
        }
        result.put("error", "Container full");
        return result;
    }

    public Map<String, Object> extractFromContainer(int x, int y, int z, int containerSlot, int count) {
        Map<String, Object> result = new LinkedHashMap<>();
        BlockPos pos = new BlockPos(x, y, z);
        var blockEntity = player.level().getBlockEntity(pos);
        if (!(blockEntity instanceof net.minecraft.world.Container container)) {
            result.put("error", "No container at position");
            return result;
        }
        if (containerSlot < 0 || containerSlot >= container.getContainerSize()) {
            result.put("error", "Invalid container slot");
            return result;
        }
        ItemStack source = container.getItem(containerSlot);
        if (source.isEmpty()) {
            result.put("error", "Empty container slot");
            return result;
        }
        int toExtract = Math.min(count, source.getCount());
        ItemStack extracted = source.split(toExtract);
        if (!player.getInventory().add(extracted)) {
            source.grow(extracted.getCount());
            result.put("error", "Bot inventory full");
            return result;
        }
        container.setChanged();
        result.put("status", "extracted");
        result.put("item", BuiltInRegistries.ITEM.getKey(extracted.getItem()).toString());
        result.put("count", toExtract);
        return result;
    }

    public Map<String, Object> extractFromContainerByItem(int x, int y, int z, String itemId, int count) {
        Map<String, Object> result = new LinkedHashMap<>();
        BlockPos pos = new BlockPos(x, y, z);
        var blockEntity = player.level().getBlockEntity(pos);
        if (!(blockEntity instanceof net.minecraft.world.Container container)) {
            result.put("error", "No container at position");
            return result;
        }
        net.minecraft.world.item.Item targetItem;
        try {
            targetItem = BuiltInRegistries.ITEM.get(net.minecraft.resources.ResourceLocation.parse(itemId));
        } catch (Exception e) {
            result.put("error", "Invalid item ID: " + itemId);
            return result;
        }
        int totalExtracted = 0;
        for (int slot = 0; slot < container.getContainerSize() && totalExtracted < count; slot++) {
            ItemStack source = container.getItem(slot);
            if (source.isEmpty() || source.getItem() != targetItem) continue;
            int toExtract = Math.min(count - totalExtracted, source.getCount());
            ItemStack extracted = source.split(toExtract);
            if (!player.getInventory().add(extracted)) {
                source.grow(extracted.getCount());
                if (totalExtracted == 0) {
                    result.put("error", "Bot inventory full");
                    return result;
                }
                break;
            }
            totalExtracted += toExtract;
        }
        if (totalExtracted == 0) {
            result.put("error", "Item not found in container: " + itemId);
            return result;
        }
        container.setChanged();
        result.put("status", "extracted");
        result.put("item", itemId);
        result.put("count", totalExtracted);
        return result;
    }

    // ── Recipe queries ──

    public List<Map<String, Object>> listRecipes(String filter, boolean craftableOnly) {
        List<Map<String, Object>> result = new ArrayList<>();
        var server = player.getServer();
        var allRecipes = server.getRecipeManager().getAllRecipesFor(net.minecraft.world.item.crafting.RecipeType.CRAFTING);
        String search = filter != null ? filter.toLowerCase() : "";

        for (var holder : allRecipes) {
            ItemStack output = holder.value().getResultItem(server.registryAccess());
            if (output.isEmpty()) continue;

            String outputId = BuiltInRegistries.ITEM.getKey(output.getItem()).toString();
            String outputName = output.getHoverName().getString().toLowerCase();
            if (!search.isEmpty() && !outputId.contains(search) && !outputName.contains(search)) {
                continue;
            }

            var ingredients = holder.value().getIngredients();
            List<String> ingredientNames = new ArrayList<>();
            boolean canCraft = true;

            for (var ing : ingredients) {
                if (ing.isEmpty()) continue;
                ItemStack[] items = ing.getItems();
                if (items.length > 0) {
                    ingredientNames.add(BuiltInRegistries.ITEM.getKey(items[0].getItem()).toString());
                    if (craftableOnly) {
                        boolean found = false;
                        for (int s = 0; s < player.getInventory().getContainerSize(); s++) {
                            if (ing.test(player.getInventory().getItem(s))) {
                                found = true;
                                break;
                            }
                        }
                        if (!found) canCraft = false;
                    }
                }
            }

            if (craftableOnly && !canCraft) continue;

            Map<String, Object> recipe = new LinkedHashMap<>();
            recipe.put("output", outputId);
            recipe.put("output_name", output.getHoverName().getString());
            recipe.put("output_count", output.getCount());
            recipe.put("ingredients", ingredientNames);
            recipe.put("craftable", canCraft);
            result.add(recipe);
            if (result.size() >= 50) break;
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

    // ── Equipment queries ──

    public SimpleContainer getExtendedInventory() {
        return extendedInventory;
    }

    /**
     * Central delivery helper. ANY code path that gives items to a bot must
     * route through here — a raw {@code inventory.add()} silently discards
     * overflow, which is the bug class this vault exists to eliminate
     * (findings 16, 27, and the ConjureAction gap caught in v4 verification).
     * Falls back to a plain add for non-bot players.
     */
    public static int deliverTo(ServerPlayer player, ItemStack stack) {
        if (stack == null || stack.isEmpty()) return 0;
        BotPlayer bot = BotManager.getBot(player.getName().getString());
        if (bot != null) return bot.deliver(stack);
        int n = stack.getCount();
        player.getInventory().add(stack);
        if (!stack.isEmpty()) player.drop(stack.copy(), false);
        return n;
    }

    public BotVault getVault() {
        return vault;
    }

    // ── Vault paging ──────────────────────────────────────────────────────
    // The carried inventory is a working set; the vault is the backing store.
    // Behaviors call these instead of letting deliveries evaporate or drop.

    /** Slots free in the carried inventory (main 36 only, not armor/offhand). */
    public int freeSlots() {
        int free = 0;
        for (int i = 0; i < 36; i++) {
            if (player.getInventory().getItem(i).isEmpty()) free++;
        }
        return free;
    }

    /**
     * Deliver items to the bot: into carried inventory if there's room,
     * overflow into the vault. Never drops, never evaporates.
     * Returns the number delivered (always the full amount).
     */
    public int deliver(ItemStack stack) {
        if (stack == null || stack.isEmpty()) return 0;
        int total = stack.getCount();
        ItemStack working = stack.copy();
        player.getInventory().add(working);
        if (!working.isEmpty()) {
            vault.deposit(working);
        }
        stack.setCount(0);
        return total;
    }

    /**
     * Free up carried slots by paging evictable items into the vault.
     * Retention policy: never evict equipped gear, the pinned material of the
     * active directive, tools, or one stack of food. Largest stacks go first
     * (biggest space win per transfer). Returns slots freed.
     */
    public int flushToVault(int slotsWanted, String pinnedItemId) {
        if (slotsWanted <= 0) return 0;
        String pinned = pinnedItemId == null ? "" : pinnedItemId.toLowerCase();
        boolean keptFood = false;
        record Candidate(int slot, int count) {}
        List<Candidate> candidates = new ArrayList<>();

        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().toLowerCase();
            if (!pinned.isEmpty() && id.contains(pinned.replace("minecraft:", ""))) continue;
            if (stack.getItem() instanceof net.minecraft.world.item.TieredItem) continue;   // tools/weapons
            if (stack.getItem() instanceof net.minecraft.world.item.ArmorItem) continue;
            if (stack.getItem() instanceof net.minecraft.world.item.ShieldItem) continue;
            if (stack.getFoodProperties(player) != null) {
                if (!keptFood) { keptFood = true; continue; }   // keep one food stack
            }
            candidates.add(new Candidate(i, stack.getCount()));
        }

        candidates.sort((a, b) -> Integer.compare(b.count(), a.count()));
        int freed = 0;
        for (Candidate c : candidates) {
            if (freed >= slotsWanted) break;
            ItemStack stack = player.getInventory().getItem(c.slot());
            if (stack.isEmpty()) continue;
            vault.deposit(stack.copy());
            player.getInventory().setItem(c.slot(), ItemStack.EMPTY);
            freed++;
        }
        if (freed > 0) {
            AIPlayerMod.LOGGER.info("[{}] Paged {} stack(s) to vault (pinned={})",
                    player.getName().getString(), freed, pinned.isEmpty() ? "none" : pinned);
        }
        return freed;
    }

    /**
     * Ensure at least {@code needed} of an item is in the carried inventory,
     * pulling from the vault if short. Returns the carried count afterwards.
     */
    public int ensureCarried(String itemId, int needed) {
        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(
                itemId.contains(":") ? itemId : "minecraft:" + itemId));
        if (item == Items.AIR) return 0;
        int carried = countCarried(item);
        if (carried >= needed) return carried;
        int short_ = needed - carried;
        if (freeSlots() < 1) flushToVault(2, itemId);
        int moved = vault.withdrawInto(player.getInventory(), itemId, short_);
        if (moved > 0) {
            AIPlayerMod.LOGGER.info("[{}] Withdrew {}x {} from vault",
                    player.getName().getString(), moved, itemId);
        }
        return carried + moved;
    }

    private int countCarried(Item item) {
        int total = 0;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (s.is(item)) total += s.getCount();
        }
        return total;
    }

    /**
     * Store carried items into the vault. A null item flushes everything
     * evictable (keeping gear + one food stack); a named item stores up to
     * {@code amount} of it.
     */
    public Map<String, Object> storeToVault(String itemId, int amount) {
        int stored = 0;
        if (itemId == null || itemId.isEmpty()) {
            int freed = flushToVault(36, null);
            return Map.of("stored_stacks", freed, "mode", "flush_all");
        }
        Item want = BuiltInRegistries.ITEM.get(ResourceLocation.parse(
                itemId.contains(":") ? itemId : "minecraft:" + itemId));
        if (want == Items.AIR) return Map.of("error", "unknown item: " + itemId);
        int remaining = amount;
        for (int i = 0; i < 36 && remaining > 0; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty() || !stack.is(want)) continue;
            int take = Math.min(stack.getCount(), remaining);
            ItemStack moved = stack.copy();
            moved.setCount(take);
            vault.deposit(moved);
            stack.shrink(take);
            if (stack.isEmpty()) player.getInventory().setItem(i, ItemStack.EMPTY);
            stored += take;
            remaining -= take;
        }
        return Map.of("stored", stored, "item", itemId);
    }

    /** Carried + vault totals, merged by item id — the bot's real holdings. */
    public List<Map<String, Object>> getEffectiveInventory() {
        Map<String, Map<String, Object>> merged = new LinkedHashMap<>();
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
            Map<String, Object> e = merged.computeIfAbsent(id, k -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("item", id);
                m.put("name", stack.getHoverName().getString());
                m.put("carried", 0);
                m.put("vault", 0);
                m.put("count", 0);
                return m;
            });
            e.put("carried", (int) e.get("carried") + stack.getCount());
            e.put("count", (int) e.get("count") + stack.getCount());
        }
        for (Map<String, Object> v : vault.manifest()) {
            String id = (String) v.get("item");
            Map<String, Object> e = merged.computeIfAbsent(id, k -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("item", id);
                m.put("name", v.get("name"));
                m.put("carried", 0);
                m.put("vault", 0);
                m.put("count", 0);
                return m;
            });
            e.put("vault", (int) e.get("vault") + (int) v.get("count"));
            e.put("count", (int) e.get("count") + (int) v.get("count"));
        }
        return new ArrayList<>(merged.values());
    }

    public Map<String, Object> getEquipment() {
        Map<String, Object> result = new LinkedHashMap<>();
        for (EquipmentSlot slot : EquipmentSlot.values()) {
            ItemStack stack = getEquippedItem(slot);
            if (!stack.isEmpty()) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("item", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
                item.put("name", stack.getHoverName().getString());
                item.put("count", stack.getCount());
                result.put(slot.getName(), item);
            }
        }
        return result;
    }

    public List<Map<String, Object>> getExtendedInventoryItems() {
        List<Map<String, Object>> result = new ArrayList<>();
        for (int i = 0; i < extendedInventory.getContainerSize(); i++) {
            ItemStack stack = extendedInventory.getItem(i);
            if (!stack.isEmpty()) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("slot", i);
                item.put("item", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
                item.put("name", stack.getHoverName().getString());
                item.put("count", stack.getCount());
                result.add(item);
            }
        }
        return result;
    }

    // ── Interaction ──

    public boolean isLookingAt(ServerPlayer viewer, double maxDistance) {
        Vec3 eye = viewer.getEyePosition();
        Vec3 look = viewer.getLookAngle();
        Vec3 botPos = player.position().add(0, 0.9, 0);

        for (double d = 0.5; d <= maxDistance; d += 0.25) {
            Vec3 point = eye.add(look.scale(d));
            if (point.distanceTo(botPos) < 1.2) {
                return true;
            }
        }
        return false;
    }

    private int transmuteScanSlot = 0;
    private static final int TRANSMUTE_SCAN_SLOTS_PER_TICK = 4;

    private void scanInventoryForTransmutables() {
        long tick = player.server.getTickCount();
        int totalSlots = player.getInventory().getContainerSize();
        for (int i = 0; i < TRANSMUTE_SCAN_SLOTS_PER_TICK; i++) {
            if (transmuteScanSlot >= totalSlots) {
                transmuteScanSlot = 0;
                return;
            }
            ItemStack stack = player.getInventory().getItem(transmuteScanSlot);
            if (!stack.isEmpty()) {
                TransmuteRegistry.discover(stack, player.getName().getString(), tick);
                EnchantmentRegistry.discoverFromItem(stack, player.getName().getString());
            }
            transmuteScanSlot++;
        }
    }

    private Map<String, Integer> formatBlockPos(BlockPos pos) {
        Map<String, Integer> map = new LinkedHashMap<>();
        map.put("x", pos.getX());
        map.put("y", pos.getY());
        map.put("z", pos.getZ());
        return map;
    }
}
