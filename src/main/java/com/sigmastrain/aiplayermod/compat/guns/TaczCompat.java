package com.sigmastrain.aiplayermod.compat.guns;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.item.ItemStack;

import java.lang.reflect.Method;
import java.util.function.Supplier;

/**
 * Timeless and Classics Zero (TaCZ 1.1.7) bridge — reflection-only, the modpack
 * is frozen and TaCZ is optional.
 *
 * <p>TaCZ mixes {@code IGunOperator} into every LivingEntity; a real player's
 * client sends draw/reload/shoot packets whose server handlers call exactly the
 * methods used here ({@code ClientMessagePlayerShoot} → {@code
 * IGunOperator.fromLivingEntity(p).shoot(()->xRot, ()->yRot, ts)}). A bot has no
 * client, so we drive the operator directly. Verified against the jar:
 * {@code draw(Supplier<ItemStack>)}, {@code reload()}, {@code bolt()},
 * {@code shoot(Supplier<Float>, Supplier<Float>)} (2-arg form computes a valid
 * network timestamp) → {@code ShootResult}; {@code IGun.getIGunOrNull(ItemStack)}.
 */
public final class TaczCompat {

    private TaczCompat() {}

    private static volatile Boolean resolved;
    private static Method fromLivingEntity, draw, reload, bolt, shoot2, getIGunOrNull;

    public static boolean isAvailable() {
        return ModCompat.isTaczLoaded() && resolve();
    }

    /** True if the stack is a TaCZ gun. */
    public static boolean isGun(ItemStack stack) {
        if (stack.isEmpty() || !isAvailable()) return false;
        try {
            return getIGunOrNull.invoke(null, stack) != null;
        } catch (Exception e) {
            return false;
        }
    }

    /** Draw the main-hand gun (what a client does on hand change). */
    public static void draw(ServerPlayer bot) {
        if (!isAvailable()) return;
        try {
            Object op = fromLivingEntity.invoke(null, bot);
            Supplier<ItemStack> sup = bot::getMainHandItem;
            draw.invoke(op, sup);
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[TaczCompat] draw failed: {}", e.toString());
        }
    }

    public static void reload(ServerPlayer bot) {
        if (!isAvailable()) return;
        try {
            reload.invoke(fromLivingEntity.invoke(null, bot));
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[TaczCompat] reload failed: {}", e.toString());
        }
    }

    public static void bolt(ServerPlayer bot) {
        if (!isAvailable()) return;
        try {
            bolt.invoke(fromLivingEntity.invoke(null, bot));
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[TaczCompat] bolt failed: {}", e.toString());
        }
    }

    /**
     * Fire the drawn gun along the bot's current look. Returns the TaCZ
     * {@code ShootResult} name (SUCCESS, NO_AMMO, NOT_DRAW, NEED_BOLT, COOL_DOWN,
     * IS_RELOADING, ...) or "ERROR".
     */
    public static String shoot(ServerPlayer bot) {
        if (!isAvailable()) return "ERROR";
        try {
            Object op = fromLivingEntity.invoke(null, bot);
            Supplier<Float> pitch = bot::getXRot;
            Supplier<Float> yaw = bot::getYRot;
            Object result = shoot2.invoke(op, pitch, yaw);
            return result == null ? "ERROR" : result.toString();
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[TaczCompat] shoot failed: {}", e.toString());
            return "ERROR";
        }
    }

    private static boolean resolve() {
        Boolean r = resolved;
        if (r != null) return r;
        synchronized (TaczCompat.class) {
            if (resolved != null) return resolved;
            try {
                Class<?> opCls = Class.forName("com.tacz.guns.api.entity.IGunOperator");
                fromLivingEntity = opCls.getMethod("fromLivingEntity", LivingEntity.class);
                draw = opCls.getMethod("draw", Supplier.class);
                reload = opCls.getMethod("reload");
                bolt = opCls.getMethod("bolt");
                shoot2 = opCls.getMethod("shoot", Supplier.class, Supplier.class);
                Class<?> iGun = Class.forName("com.tacz.guns.api.item.IGun");
                getIGunOrNull = iGun.getMethod("getIGunOrNull", ItemStack.class);
                resolved = true;
                AIPlayerMod.LOGGER.info("[TaczCompat] TaCZ gun operator wired for bots");
            } catch (Throwable t) {
                resolved = false;
                AIPlayerMod.LOGGER.warn("[TaczCompat] TaCZ API not resolvable ({}); bots won't use TaCZ guns", t.toString());
            }
            return resolved;
        }
    }
}
