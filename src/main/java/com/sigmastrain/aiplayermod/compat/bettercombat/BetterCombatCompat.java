package com.sigmastrain.aiplayermod.compat.bettercombat;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.network.protocol.game.ClientboundAnimatePacket;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;

public final class BetterCombatCompat {

    private BetterCombatCompat() {}

    public static boolean isAvailable() {
        return ModCompat.isBetterCombatLoaded();
    }

    /**
     * Attempts to broadcast a Better Combat attack animation for the given player's held weapon.
     * Returns true if a BC animation was sent, false if vanilla fallback should be used.
     */
    public static boolean broadcastAttackAnimation(ServerPlayer player) {
        if (!isAvailable()) return false;

        try {
            return doBroadcastAnimation(player);
        } catch (Exception e) {
            AIPlayerMod.LOGGER.warn("[BetterCombatCompat] Animation dispatch failed, falling back to vanilla: {}",
                    e.getMessage());
            return false;
        }
    }

    private static boolean doBroadcastAnimation(ServerPlayer player) {
        ItemStack weapon = player.getMainHandItem();
        if (weapon.isEmpty()) return false;

        // Better Combat registers weapon animations via its WeaponRegistry.
        // The animation data is stored on items via data components / NBT.
        // We check if the weapon has a BC animation attribute.
        if (!hasBetterCombatAnimation(weapon)) return false;

        // Better Combat uses a custom C2S packet (PlayerAttackAnimationC2S) which the server then
        // rebroadcasts via S2C (PlayerAttackAnimationS2C). For fake players we directly construct
        // and broadcast the S2C animation packet.
        broadcastBCAnimation(player, weapon);
        return true;
    }

    private static boolean hasBetterCombatAnimation(ItemStack weapon) {
        // Better Combat stores weapon animation data in the item's custom data or via its registry.
        // Check if the item type has a registered attack animation in BC's system.
        // BC uses a ResourceLocation-based registry tied to item tags or direct registration.
        try {
            Class<?> weaponRegistryClass = Class.forName("net.bettercombat.api.WeaponAttributes");
            // If the class exists, BC is loaded. Check if weapon has attributes via BC's API.
            var method = Class.forName("net.bettercombat.logic.WeaponRegistry")
                    .getMethod("getAttributes", ItemStack.class);
            Object attributes = method.invoke(null, weapon);
            return attributes != null;
        } catch (ClassNotFoundException e) {
            return false;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[BetterCombatCompat] Could not check weapon animation: {}", e.getMessage());
            return false;
        }
    }

    private static void broadcastBCAnimation(ServerPlayer botPlayer, ItemStack weapon) {
        try {
            // Better Combat's server-side animation broadcast.
            // The mod uses a fabric networking / NeoForge payload system.
            // We invoke its animation handler to broadcast the swing to all nearby players.
            Class<?> serverNetworkClass = Class.forName("net.bettercombat.network.ServerNetwork");
            var broadcastMethod = serverNetworkClass.getMethod("broadcastAttackAnimation",
                    ServerPlayer.class, int.class, boolean.class);
            // combo count 0 = first swing, isSneaking = false
            broadcastMethod.invoke(null, botPlayer, 0, false);
        } catch (ClassNotFoundException e) {
            // BC doesn't have this exact API - fall back to sending a standard swing
            // but attempt via BC's animation packet directly
            sendFallbackBCPacket(botPlayer);
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[BetterCombatCompat] Could not broadcast BC animation: {}", e.getMessage());
            sendFallbackBCPacket(botPlayer);
        }
    }

    private static void sendFallbackBCPacket(ServerPlayer botPlayer) {
        // If we can't use BC's high-level API, send the vanilla swing as a baseline.
        // BC clients will still render their weapon-specific animation from the swing event.
        if (botPlayer.level() instanceof ServerLevel sl) {
            var swingPacket = new ClientboundAnimatePacket(botPlayer, ClientboundAnimatePacket.SWING_MAIN_HAND);
            for (ServerPlayer online : sl.getServer().getPlayerList().getPlayers()) {
                online.connection.send(swingPacket);
            }
        }
    }
}
