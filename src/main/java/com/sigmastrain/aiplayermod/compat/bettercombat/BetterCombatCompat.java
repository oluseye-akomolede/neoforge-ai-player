package com.sigmastrain.aiplayermod.compat.bettercombat;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.neoforged.neoforge.network.PacketDistributor;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Better Combat (2.3.x) attack-animation bridge for bots. Reflection-only —
 * the modpack is frozen and BC is an optional dependency.
 *
 * <p>Why this exists: for a real player, BC's <em>client</em> computes the
 * attack animation and sends {@code Packets$AttackAnimation} C2S; the server
 * simply forwards that packet to everyone tracking the player
 * ({@code ServerNetwork.handleAttackAnimation}). A bot has no client, so nobody
 * ever emits that packet — and BC (via player-animation-lib) drives the arms
 * of a player holding a BC-attributed weapon, which is exactly why a plain
 * vanilla {@code ClientboundAnimatePacket} swing never shows on a drone
 * wielding a sword. This class builds the same S2C packet BC's own client
 * would have produced ({@code MinecraftClientInject.startUpswing}) and
 * broadcasts it, so bots animate the way players do.
 *
 * <p>Verified against {@code bettercombat-neoforge-2.3.2+1.21.1.jar}:
 * {@code Packets$AttackAnimation(int playerId, AnimatedHand, String animation,
 * float length, float upswing, float weaponRange, int upswingTicks,
 * Packets$SwingParticles)}, {@code AnimatedHand.from(boolean offHand, boolean
 * twoHanded)}, {@code WeaponRegistry.getAttributes(ItemStack)},
 * {@code WeaponAttributes.attacks()/isTwoHanded()/attackRange()},
 * {@code WeaponAttributes$Attack.animation()/upswing()},
 * {@code PlayerAttackHelper.getAttackCooldownTicksCapped(Player)}.
 */
public final class BetterCombatCompat {

    private BetterCombatCompat() {}

    /** Per-bot combo index so successive swings cycle a weapon's attack chain like a player's do. */
    private static final Map<UUID, Integer> COMBO = new ConcurrentHashMap<>();

    // Resolved lazily; null once resolution has failed so we don't retry every swing.
    private static volatile Boolean resolved;
    private static Method getAttributes, attacks, isTwoHanded, attackRange, animation, upswing, animatedHandFrom, cooldownTicks;
    private static Constructor<?> packetCtor;
    private static Object emptyParticles;

    public static boolean isAvailable() {
        return ModCompat.isBetterCombatLoaded();
    }

    /** Does this stack carry BC weapon attributes (i.e. will BC animate it)? */
    public static boolean hasBetterCombatAnimation(ItemStack weapon) {
        if (weapon.isEmpty() || !isAvailable() || !resolve()) return false;
        try {
            return getAttributes.invoke(null, weapon) != null;
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * Broadcast a genuine Better Combat attack animation for the player's held
     * weapon. Returns true if a BC animation was sent, false if the caller should
     * fall back to a vanilla swing (weapon has no BC attributes, or BC absent).
     */
    public static boolean broadcastAttackAnimation(ServerPlayer player) {
        if (!isAvailable() || !resolve()) return false;
        try {
            return doBroadcastAnimation(player);
        } catch (Exception e) {
            AIPlayerMod.LOGGER.warn("[BetterCombatCompat] Animation dispatch failed, falling back to vanilla: {}",
                    e.toString());
            return false;
        }
    }

    private static boolean doBroadcastAnimation(ServerPlayer player) throws Exception {
        ItemStack weapon = player.getMainHandItem();
        if (weapon.isEmpty()) return false;
        if (!(player.level() instanceof ServerLevel sl)) return false;

        Object attributes = getAttributes.invoke(null, weapon);
        if (attributes == null) return false;
        Object[] attackChain = (Object[]) attacks.invoke(attributes);
        if (attackChain == null || attackChain.length == 0) return false;

        int combo = COMBO.merge(player.getUUID(), 1, Integer::sum) % attackChain.length;
        Object attack = attackChain[combo];

        String animName = (String) animation.invoke(attack);
        if (animName == null || animName.isEmpty()) return false;
        float upswingRate = ((Number) upswing.invoke(attack)).floatValue();
        boolean twoHanded = (Boolean) isTwoHanded.invoke(attributes);
        float range = ((Number) attackRange.invoke(attributes)).floatValue();
        Object animatedHand = animatedHandFrom.invoke(null, false, twoHanded);

        float cooldown;
        try {
            cooldown = ((Number) cooldownTicks.invoke(null, player)).floatValue();
        } catch (Exception e) {
            cooldown = player.getCurrentItemAttackStrengthDelay();
        }
        int upswingTicks = Math.max(Math.round(cooldown * upswingRate), 1);

        Object pkt = packetCtor.newInstance(player.getId(), animatedHand, animName,
                cooldown, upswingRate, range, upswingTicks, emptyParticles);
        CustomPacketPayload payload = (CustomPacketPayload) pkt;

        for (ServerPlayer online : sl.getServer().getPlayerList().getPlayers()) {
            if (online == player) continue;                // the bot has no client
            PacketDistributor.sendToPlayer(online, payload);
        }
        return true;
    }

    private static boolean resolve() {
        Boolean r = resolved;
        if (r != null) return r;
        synchronized (BetterCombatCompat.class) {
            if (resolved != null) return resolved;
            try {
                Class<?> registry = Class.forName("net.bettercombat.logic.WeaponRegistry");
                getAttributes = registry.getMethod("getAttributes", ItemStack.class);
                Class<?> attrs = Class.forName("net.bettercombat.api.WeaponAttributes");
                attacks = attrs.getMethod("attacks");
                isTwoHanded = attrs.getMethod("isTwoHanded");
                attackRange = attrs.getMethod("attackRange");
                Class<?> attackCls = Class.forName("net.bettercombat.api.WeaponAttributes$Attack");
                animation = attackCls.getMethod("animation");
                upswing = attackCls.getMethod("upswing");
                Class<?> handCls = Class.forName("net.bettercombat.logic.AnimatedHand");
                animatedHandFrom = handCls.getMethod("from", boolean.class, boolean.class);
                cooldownTicks = Class.forName("net.bettercombat.logic.PlayerAttackHelper")
                        .getMethod("getAttackCooldownTicksCapped", Player.class);
                Class<?> particlesCls = Class.forName("net.bettercombat.network.Packets$SwingParticles");
                emptyParticles = particlesCls.getField("EMPTY").get(null);
                Class<?> pktCls = Class.forName("net.bettercombat.network.Packets$AttackAnimation");
                packetCtor = pktCls.getConstructor(int.class, handCls, String.class,
                        float.class, float.class, float.class, int.class, particlesCls);
                resolved = true;
                AIPlayerMod.LOGGER.info("[BetterCombatCompat] Better Combat attack animations wired for bots");
            } catch (Throwable t) {
                resolved = false;
                AIPlayerMod.LOGGER.warn("[BetterCombatCompat] Better Combat API not resolvable ({}); bots will use vanilla swings",
                        t.toString());
            }
            return resolved;
        }
    }
}
