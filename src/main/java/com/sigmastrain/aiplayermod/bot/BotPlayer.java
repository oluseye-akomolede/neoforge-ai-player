package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.actions.ActionQueue;
import com.sigmastrain.aiplayermod.brain.BotBrain;
import com.sigmastrain.aiplayermod.shop.EnchantmentRegistry;
import com.sigmastrain.aiplayermod.shop.TransmuteRegistry;
import com.mojang.authlib.GameProfile;
import net.minecraft.core.BlockPos;
import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.network.chat.Style;
import net.minecraft.network.protocol.game.*;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.resources.ResourceKey;
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
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
import net.minecraft.core.registries.BuiltInRegistries;

import net.minecraft.world.SimpleContainer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.ai.attributes.Attributes;

import java.util.*;
import java.util.concurrent.ConcurrentLinkedQueue;

public class BotPlayer {
    private final ServerPlayer player;
    private final ActionQueue actionQueue;
    private final BotBrain brain;
    private boolean alive = true;

    private final SimpleContainer extendedInventory = new SimpleContainer(54);
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

        // Do NOT add the bot to the level or PlayerList — any method of registering
        // a ServerPlayer entity with the level causes it to appear in level.players(),
        // which FTB Chunks iterates on real player login (NPE on missing team data).
        // Instead, handle all client visibility via manual packet sending.
        BotPlayer bot = new BotPlayer(botPlayer);
        bot.broadcastSpawn();

        // Grant starting XP pool (10,000 points ≈ 53 levels)
        botPlayer.giveExperiencePoints(10000);

        server.execute(() -> PmmoCompat.setupBotSkills(botPlayer));

        return bot;
    }

    // ── Packet-based visibility ──

    private void broadcastSpawn() {
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) {
            sendSpawnPackets(online);
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
        ClientboundTeleportEntityPacket teleport = new ClientboundTeleportEntityPacket(player);
        ClientboundRotateHeadPacket head = new ClientboundRotateHeadPacket(player,
                (byte) ((int) (player.getYHeadRot() * 256.0f / 360.0f)));
        for (ServerPlayer online : player.getServer().getPlayerList().getPlayers()) {
            online.connection.send(teleport);
            online.connection.send(head);
        }
    }

    public void remove() {
        if (!alive) return;
        alive = false;
        actionQueue.clear();
        PlayerList playerList = player.getServer().getPlayerList();
        playerList.broadcastAll(new ClientboundRemoveEntitiesPacket(player.getId()));
        playerList.broadcastAll(new ClientboundPlayerInfoRemovePacket(List.of(player.getUUID())));
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
        } catch (UnsupportedOperationException e) {
            if (e.getMessage() != null && e.getMessage().contains("may not be sent to the client")) {
                AIPlayerMod.LOGGER.debug("Suppressed mod packet error for bot {}: {}", player.getName().getString(), e.getMessage());
            } else {
                AIPlayerMod.LOGGER.error("Action error for bot {}: {}", player.getName().getString(), e.getMessage());
            }
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("Action error for bot {}: {}", player.getName().getString(), e.getMessage(), e);
            actionQueue.clear();
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

    public boolean teleportToDimension(ResourceKey<Level> dimension, double x, double y, double z) {
        if (!isAlive()) return false;
        MinecraftServer server = player.getServer();
        ServerLevel targetLevel = server.getLevel(dimension);
        if (targetLevel == null) return false;

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
        status.put("xp_level", player.experienceLevel);
        status.put("xp_points", player.totalExperience);
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
