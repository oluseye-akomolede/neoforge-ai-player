package com.sigmastrain.aiplayermod.compat.guns;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.item.ItemStack;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.UUID;

/**
 * Superb Warfare (0.8.9) hand-gun bridge — reflection-only.
 *
 * <p>SW's shoot path has no client-only gate and no Player requirement: the
 * {@code ShootMessage} handler is literally
 * {@code GunData.from(mainHand).shoot(player, spread, zoom, uuid)}. Reload
 * countdown ticks server-side through {@code GunItem.inventoryTick} while the
 * gun sits in the bot's main hand, so a bot only has to <em>start</em> a reload
 * ({@code GunEventHandler.INSTANCE.tryStartReload(entity, data)}). Player-ammo
 * guns (rifle/heavy/... counters stored on the entity) are fed by converting
 * carried {@code AmmoSupplierItem}s exactly the way the item's own use() does:
 * {@code item.getType().add(entity, item.getAmmoToAdd())}.
 */
public final class SwGunCompat {

    private SwGunCompat() {}

    private static volatile Boolean resolved;
    private static Class<?> gunItemCls, ammoSupplierCls;
    private static Method dataFrom, dataShoot, dataCanShoot, dataReloading, dataGet,
            dataSelectedConsumer, dataHasEnoughAmmo, dataSave,
            consumerGetType, consumerGetPlayerAmmoType,
            ammoAdd, ammoGetEntity, supplierGetType, supplierGetAmmoToAdd,
            handlerTryStartReload, ammoGetItemStackN, consumerStack;
    private static Object handlerInstance, propRpm;

    public static boolean isAvailable() {
        return ModCompat.isSuperbWarfareLoaded() && resolve();
    }

    public static boolean isGun(ItemStack stack) {
        return !stack.isEmpty() && isAvailable() && gunItemCls.isInstance(stack.getItem());
    }

    /** SW's own composite gate: ammo, heat, reload/charge state, bolt. */
    public static boolean canShoot(ServerPlayer bot, ItemStack gun) {
        if (!isGun(gun)) return false;
        try {
            Object data = dataFrom.invoke(null, gun);
            return (Boolean) dataCanShoot.invoke(data, bot);
        } catch (Exception e) {
            return false;
        }
    }

    public static boolean reloading(ItemStack gun) {
        if (!isGun(gun)) return false;
        try {
            return (Boolean) dataReloading.invoke(dataFrom.invoke(null, gun));
        } catch (Exception e) {
            return false;
        }
    }

    public static boolean hasAmmo(ServerPlayer bot, ItemStack gun) {
        if (!isGun(gun)) return false;
        try {
            return (Boolean) dataHasEnoughAmmo.invoke(dataFrom.invoke(null, gun), bot);
        } catch (Exception e) {
            return false;
        }
    }

    /** Rounds per minute of the gun, or -1. */
    public static int rpm(ItemStack gun) {
        if (!isGun(gun) || propRpm == null) return -1;
        try {
            Object v = dataGet.invoke(dataFrom.invoke(null, gun), propRpm);
            return v instanceof Number n ? n.intValue() : -1;
        } catch (Exception e) {
            return -1;
        }
    }

    /** Fire along the bot's look vector. True if the call went through. */
    public static boolean shoot(ServerPlayer bot, ItemStack gun) {
        if (!isGun(gun)) return false;
        try {
            Object data = dataFrom.invoke(null, gun);
            dataShoot.invoke(data, bot, 0.0d, false, (UUID) null);
            return true;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[SwGunCompat] shoot failed: {}", e.toString());
            return false;
        }
    }

    /** Begin a reload; the countdown runs in SW's own inventory tick. */
    public static void tryReload(ServerPlayer bot, ItemStack gun) {
        if (!isGun(gun)) return;
        try {
            Object data = dataFrom.invoke(null, gun);
            handlerTryStartReload.invoke(handlerInstance, bot, data);
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[SwGunCompat] tryStartReload failed: {}", e.toString());
        }
    }

    /**
     * For player-ammo guns: if the entity's counter for the gun's ammo type is
     * empty, consume one carried {@code AmmoSupplierItem} of that type into the
     * counter. Returns true if ammo was fed.
     */
    public static boolean feedPlayerAmmo(ServerPlayer bot, ItemStack gun) {
        if (!isGun(gun) || ammoSupplierCls == null) return false;
        try {
            Object data = dataFrom.invoke(null, gun);
            Object consumer = dataSelectedConsumer.invoke(data);
            if (consumer == null) return false;
            Object type = consumerGetType.invoke(consumer);
            if (type == null || !"PLAYER_AMMO".equals(type.toString())) return false;
            Object ammoType = consumerGetPlayerAmmoType.invoke(consumer);
            if (ammoType == null) return false;
            int have = (Integer) ammoGetEntity.invoke(ammoType, bot);
            if (have > 0) return false;
            var inv = bot.getInventory();
            for (int i = 0; i < inv.getContainerSize(); i++) {
                ItemStack s = inv.getItem(i);
                if (s.isEmpty() || !ammoSupplierCls.isInstance(s.getItem())) continue;
                Object itemType = supplierGetType.invoke(s.getItem());
                if (itemType != ammoType) continue;
                int add = (Integer) supplierGetAmmoToAdd.invoke(s.getItem());
                ammoAdd.invoke(ammoType, bot, add);
                s.shrink(1);
                return true;
            }
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[SwGunCompat] feedPlayerAmmo failed: {}", e.toString());
        }
        return false;
    }

    /**
     * Ammo for an SW gun: player-ammo guns get {@code boxes} supplier items of
     * their ammo type; item-ammo guns get {@code boxes} of the ammo item. Empty if unknown.
     */
    public static ItemStack ammoStackFor(ItemStack gun, int boxes) {
        if (!isGun(gun) || boxes <= 0) return ItemStack.EMPTY;
        try {
            Object data = dataFrom.invoke(null, gun);
            Object consumer = dataSelectedConsumer.invoke(data);
            if (consumer == null) return ItemStack.EMPTY;
            String type = String.valueOf(consumerGetType.invoke(consumer));
            if ("PLAYER_AMMO".equals(type)) {
                Object ammoType = consumerGetPlayerAmmoType.invoke(consumer);
                if (ammoType == null || ammoGetItemStackN == null) return ItemStack.EMPTY;
                Object st = ammoGetItemStackN.invoke(ammoType, boxes);
                return st instanceof ItemStack s ? s : ItemStack.EMPTY;
            }
            if ("ITEM".equals(type) && consumerStack != null) {
                Object st = consumerStack.invoke(consumer);
                if (st instanceof ItemStack s && !s.isEmpty()) return s.copyWithCount(Math.min(boxes, s.getMaxStackSize()));
            }
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[SwGunCompat] ammoStackFor failed: {}", e.toString());
        }
        return ItemStack.EMPTY;
    }

    private static boolean resolve() {
        Boolean r = resolved;
        if (r != null) return r;
        synchronized (SwGunCompat.class) {
            if (resolved != null) return resolved;
            try {
                gunItemCls = Class.forName("com.atsuishio.superbwarfare.item.gun.GunItem");
                Class<?> dataCls = Class.forName("com.atsuishio.superbwarfare.data.gun.GunData");
                dataFrom = dataCls.getMethod("from", ItemStack.class);
                dataShoot = dataCls.getMethod("shoot", Entity.class, double.class, boolean.class, UUID.class);
                dataCanShoot = dataCls.getMethod("canShoot", Entity.class);
                dataReloading = dataCls.getMethod("reloading");
                dataHasEnoughAmmo = dataCls.getMethod("hasEnoughAmmoToShoot", Entity.class);
                dataSave = dataCls.getMethod("save");
                dataSelectedConsumer = dataCls.getMethod("selectedAmmoConsumer");
                Class<?> propCls = Class.forName("com.atsuishio.superbwarfare.data.gun.GunProp");
                dataGet = dataCls.getMethod("get", propCls);
                try {
                    Field f = propCls.getField("RPM");
                    propRpm = f.get(null);
                } catch (Throwable ignored) {
                    propRpm = null;
                }
                Class<?> consumerCls = Class.forName("com.atsuishio.superbwarfare.data.gun.AmmoConsumer");
                consumerGetType = consumerCls.getMethod("getType");
                consumerGetPlayerAmmoType = consumerCls.getMethod("getPlayerAmmoType");
                Class<?> ammoCls = Class.forName("com.atsuishio.superbwarfare.data.gun.Ammo");
                ammoAdd = ammoCls.getMethod("add", Entity.class, int.class);
                ammoGetEntity = ammoCls.getMethod("get", Entity.class);
                try { ammoGetItemStackN = ammoCls.getMethod("getItemStack", int.class); } catch (Throwable ignored) {}
                try { consumerStack = consumerCls.getMethod("stack"); } catch (Throwable ignored) {}
                try {
                    ammoSupplierCls = Class.forName("com.atsuishio.superbwarfare.item.ammo.AmmoSupplierItem");
                    supplierGetType = ammoSupplierCls.getMethod("getType");
                    supplierGetAmmoToAdd = ammoSupplierCls.getMethod("getAmmoToAdd");
                } catch (Throwable t) {
                    ammoSupplierCls = null;
                }
                Class<?> handlerCls = Class.forName("com.atsuishio.superbwarfare.event.GunEventHandler");
                handlerInstance = handlerCls.getField("INSTANCE").get(null);
                handlerTryStartReload = handlerCls.getMethod("tryStartReload", Entity.class, dataCls);
                resolved = true;
                AIPlayerMod.LOGGER.info("[SwGunCompat] Superb Warfare guns wired for bots");
            } catch (Throwable t) {
                resolved = false;
                AIPlayerMod.LOGGER.warn("[SwGunCompat] Superb Warfare gun API not resolvable ({}); bots won't use SW guns", t.toString());
            }
            return resolved;
        }
    }
}
