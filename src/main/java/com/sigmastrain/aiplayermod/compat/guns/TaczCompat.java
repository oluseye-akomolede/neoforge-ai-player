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
    // gun catalogue + item builders
    private static Method allCommonGunIndex, commonGunIndex, indexGetGunData, gunDataGetAmmoId, gunDataGetAmmoAmount,
            gunBuilderCreate, gunBuilderSetId, gunBuilderSetAmmoCount, gunBuilderBuild,
            ammoBuilderCreate, ammoBuilderSetId, ammoBuilderSetCount, ammoBuilderBuild, iGunGetGunId,
            iAmmoGetAmmoId, allCommonAmmoIndex;
    private static Class<?> iAmmoCls;

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

    // ── gun catalogue ────────────────────────────────────────────────────

    /** All TaCZ gun ids currently loaded ("tacz:ak47", ...). */
    @SuppressWarnings("unchecked")
    public static java.util.List<String> gunIds() {
        java.util.List<String> out = new java.util.ArrayList<>();
        if (!isAvailable() || allCommonGunIndex == null) return out;
        try {
            java.util.Set<java.util.Map.Entry<net.minecraft.resources.ResourceLocation, ?>> set =
                    (java.util.Set<java.util.Map.Entry<net.minecraft.resources.ResourceLocation, ?>>) allCommonGunIndex.invoke(null);
            for (var e : set) out.add(e.getKey().toString());
        } catch (Exception ignored) {
        }
        java.util.Collections.sort(out);
        return out;
    }

    /** Loose "ak47" / "tacz:ak47" / "AK-47" → a loaded TaCZ gun id, or null. */
    public static net.minecraft.resources.ResourceLocation resolveGunId(String query) {
        if (query == null || !isAvailable()) return null;
        String q = query.trim().toLowerCase(java.util.Locale.ROOT);
        if (q.isEmpty()) return null;
        var direct = net.minecraft.resources.ResourceLocation.tryParse(q.contains(":") ? q : "tacz:" + q);
        java.util.List<String> ids = gunIds();
        if (direct != null && ids.contains(direct.toString())) return direct;
        String nq = q.replaceAll("[^a-z0-9]", "");
        if (nq.isEmpty()) return null;
        String best = null; int bestScore = 0;
        for (String id : ids) {
            String path = id.substring(id.indexOf(':') + 1);
            String np = path.replaceAll("[^a-z0-9]", "");
            int score = 0;
            if (np.equals(nq)) score = 100;
            else if (nq.contains(np) && np.length() >= 3) score = 60 + np.length();
            else if (np.contains(nq) && nq.length() >= 3) score = 40 + nq.length();
            if (score > bestScore) { bestScore = score; best = id; }
        }
        return best == null ? null : net.minecraft.resources.ResourceLocation.parse(best);
    }

    /** Human name for a gun id (falls back to the id path). */
    public static String gunName(net.minecraft.resources.ResourceLocation gunId) {
        String key = "tacz.gun." + gunId.getNamespace() + "." + gunId.getPath();  // "tacz.gun.tacz.ak47" isn't right for all packs
        String alt = "gun." + gunId.getNamespace() + "." + gunId.getPath();
        for (String k : new String[]{key, alt}) {
            String t = net.minecraft.network.chat.Component.translatable(k).getString();
            if (!t.equals(k)) return t;
        }
        return gunId.getPath();
    }

    /** Ammo id a gun uses, or null. */
    public static net.minecraft.resources.ResourceLocation ammoIdFor(net.minecraft.resources.ResourceLocation gunId) {
        if (!isAvailable() || commonGunIndex == null) return null;
        try {
            Object opt = commonGunIndex.invoke(null, gunId);
            if (!(opt instanceof java.util.Optional<?> o) || o.isEmpty()) return null;
            Object data = indexGetGunData.invoke(o.get());
            return (net.minecraft.resources.ResourceLocation) gunDataGetAmmoId.invoke(data);
        } catch (Exception e) {
            return null;
        }
    }

    /** Magazine size of a gun, or 30. */
    public static int magazineOf(net.minecraft.resources.ResourceLocation gunId) {
        if (!isAvailable() || commonGunIndex == null) return 30;
        try {
            Object opt = commonGunIndex.invoke(null, gunId);
            if (!(opt instanceof java.util.Optional<?> o) || o.isEmpty()) return 30;
            Object data = indexGetGunData.invoke(o.get());
            return (Integer) gunDataGetAmmoAmount.invoke(data);
        } catch (Exception e) {
            return 30;
        }
    }

    /** A loaded gun item (full magazine) for the id, or empty. */
    public static ItemStack buildGun(net.minecraft.core.HolderLookup.Provider registries, net.minecraft.resources.ResourceLocation gunId) {
        if (!isAvailable() || gunBuilderCreate == null) return ItemStack.EMPTY;
        try {
            Object b = gunBuilderCreate.invoke(null);
            gunBuilderSetId.invoke(b, gunId);
            gunBuilderSetAmmoCount.invoke(b, magazineOf(gunId));
            Object stack = gunBuilderBuild.invoke(b, registries);
            return stack instanceof ItemStack st ? st : ItemStack.EMPTY;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[TaczCompat] buildGun failed: {}", e.toString());
            return ItemStack.EMPTY;
        }
    }

    /** {@code count} rounds of the ammo a gun uses (may exceed a stack: caller splits), or empty. */
    public static ItemStack buildAmmo(net.minecraft.resources.ResourceLocation gunId, int count) {
        var ammoId = ammoIdFor(gunId);
        if (ammoId == null || ammoBuilderCreate == null || count <= 0) return ItemStack.EMPTY;
        try {
            Object b = ammoBuilderCreate.invoke(null);
            ammoBuilderSetId.invoke(b, ammoId);
            ammoBuilderSetCount.invoke(b, count);
            Object stack = ammoBuilderBuild.invoke(b);
            return stack instanceof ItemStack st ? st : ItemStack.EMPTY;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[TaczCompat] buildAmmo failed: {}", e.toString());
            return ItemStack.EMPTY;
        }
    }

    /** Ammo id of a TaCZ ammo stack, or null. */
    public static net.minecraft.resources.ResourceLocation ammoIdOf(ItemStack stack) {
        if (stack.isEmpty() || !isAvailable() || iAmmoCls == null || !iAmmoCls.isInstance(stack.getItem())) return null;
        try {
            return (net.minecraft.resources.ResourceLocation) iAmmoGetAmmoId.invoke(stack.getItem(), stack);
        } catch (Exception e) {
            return null;
        }
    }

    /** Is this a loaded TaCZ ammo id? */
    @SuppressWarnings("unchecked")
    public static boolean isAmmoId(net.minecraft.resources.ResourceLocation id) {
        if (!isAvailable() || allCommonAmmoIndex == null || id == null) return false;
        try {
            var set = (java.util.Set<java.util.Map.Entry<net.minecraft.resources.ResourceLocation, ?>>) allCommonAmmoIndex.invoke(null);
            for (var e : set) if (e.getKey().equals(id)) return true;
        } catch (Exception ignored) {}
        return false;
    }

    /** {@code count} rounds of a TaCZ ammo id, or empty. */
    public static ItemStack buildAmmoById(net.minecraft.resources.ResourceLocation ammoId, int count) {
        if (ammoId == null || ammoBuilderCreate == null || count <= 0) return ItemStack.EMPTY;
        try {
            Object b = ammoBuilderCreate.invoke(null);
            ammoBuilderSetId.invoke(b, ammoId);
            ammoBuilderSetCount.invoke(b, count);
            Object stack = ammoBuilderBuild.invoke(b);
            return stack instanceof ItemStack st ? st : ItemStack.EMPTY;
        } catch (Exception e) {
            return ItemStack.EMPTY;
        }
    }

    /** The gun id carried by a TaCZ gun stack, or null. */
    public static net.minecraft.resources.ResourceLocation gunIdOf(ItemStack stack) {
        if (!isGun(stack) || iGunGetGunId == null) return null;
        try {
            Object ig = getIGunOrNull.invoke(null, stack);
            return ig == null ? null : (net.minecraft.resources.ResourceLocation) iGunGetGunId.invoke(ig, stack);
        } catch (Exception e) {
            return null;
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
                iGunGetGunId = iGun.getMethod("getGunId", ItemStack.class);
                try {
                    Class<?> api = Class.forName("com.tacz.guns.api.TimelessAPI");
                    allCommonGunIndex = api.getMethod("getAllCommonGunIndex");
                    commonGunIndex = api.getMethod("getCommonGunIndex", net.minecraft.resources.ResourceLocation.class);
                    Class<?> idx = Class.forName("com.tacz.guns.resource.index.CommonGunIndex");
                    indexGetGunData = idx.getMethod("getGunData");
                    Class<?> gd = Class.forName("com.tacz.guns.resource.pojo.data.gun.GunData");
                    gunDataGetAmmoId = gd.getMethod("getAmmoId");
                    gunDataGetAmmoAmount = gd.getMethod("getAmmoAmount");
                    Class<?> gb = Class.forName("com.tacz.guns.api.item.builder.GunItemBuilder");
                    gunBuilderCreate = gb.getMethod("create");
                    gunBuilderSetId = gb.getMethod("setId", net.minecraft.resources.ResourceLocation.class);
                    gunBuilderSetAmmoCount = gb.getMethod("setAmmoCount", int.class);
                    gunBuilderBuild = gb.getMethod("build", net.minecraft.core.HolderLookup.Provider.class);
                    Class<?> ab = Class.forName("com.tacz.guns.api.item.builder.AmmoItemBuilder");
                    ammoBuilderCreate = ab.getMethod("create");
                    ammoBuilderSetId = ab.getMethod("setId", net.minecraft.resources.ResourceLocation.class);
                    ammoBuilderSetCount = ab.getMethod("setCount", int.class);
                    ammoBuilderBuild = ab.getMethod("build");
                    allCommonAmmoIndex = api.getMethod("getAllCommonAmmoIndex");
                    iAmmoCls = Class.forName("com.tacz.guns.api.item.IAmmo");
                    iAmmoGetAmmoId = iAmmoCls.getMethod("getAmmoId", ItemStack.class);
                } catch (Throwable t) {
                    AIPlayerMod.LOGGER.warn("[TaczCompat] gun catalogue/builders unavailable ({}); guns can't be conjured", t.toString());
                }
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
