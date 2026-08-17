package com.sigmastrain.aiplayermod.compat.superbwarfare;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
import net.neoforged.neoforge.capabilities.Capabilities;
import net.neoforged.neoforge.energy.IEnergyStorage;
import net.neoforged.neoforge.items.IItemHandler;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.function.Predicate;

/**
 * Superb Warfare (0.8.9) vehicle bridge — reflection-only.
 *
 * <p>SW vehicles are server-simulated: the client's movement/fire packets are
 * thin wrappers that set synched input flags ({@code setForwardInputDown}…),
 * feed {@code mouseInput} (aircraft/helicopter yaw+pitch), or call
 * {@code vehicleShoot(seatedLiving, uuid, targetPos)}. Turrets slew toward the
 * seated occupant's view, so aiming a bot = setting its own rotation. Boarding
 * must use {@code startRiding(v, true)} — {@code VehicleEntity.interact}
 * explicitly rejects fake players. Inventory and energy are also exposed as
 * NeoForge entity capabilities, which is how we reach them without types.
 */
public final class SwVehicleCompat {

    private SwVehicleCompat() {}

    /** Broad drivability classes derived from the SW engine. */
    public enum EngineKind { LAND, BOAT, HELI, PLANE, FIXED, NONE }

    private static volatile Boolean resolved;
    private static Class<?> vehicleCls;
    private static Method getFirstPassenger, getOrderedPassengers, changeSeat, getSeatIndex, getMaxPassengers,
            hasWeaponSeat, changeWeapon, getSelectedWeaponSeat, canShoot, vehicleShoot, weaponRpm, ammoCountLiving,
            setForward, setBack, setLeft, setRight, setUp, setDown, setSprint, mouseInput,
            getEnergy, getMaxEnergy, setEnergy, hasEnergyStorage, getContainerSize, hasContainer,
            getHealth, getMaxHealth, heal, getVehicleType, getEngineInfo, isWreck, computed, seatsOf, weaponsOf,
            getGunDataLiving, dataSelectedConsumer, consumerStack, consumerGetType, consumerGetPlayerAmmoType,
            getPower, fwdDown, backDown, leftDown, rightDown, upDown, sprintDown,
            engDamaged, lWheelDamaged, rWheelDamaged, turretDamaged,
            engHealth, engMax, lWheelHealth, wheelMax, setEngHealth, setSubEngHealth, setLWheel, setRWheel, setTurretHealth, turretMax, setHealth;

    public static boolean isAvailable() {
        return ModCompat.isSuperbWarfareLoaded() && resolve();
    }

    public static boolean isVehicle(Entity e) {
        return e != null && isAvailable() && vehicleCls.isInstance(e);
    }

    /** The SW vehicle the bot is riding, or null. */
    public static Entity vehicleOf(ServerPlayer bot) {
        Entity v = bot.getVehicle();
        return isVehicle(v) ? v : null;
    }

    public static Entity nearestVehicle(ServerLevel level, Vec3 pos, double radius, Predicate<Entity> filter) {
        if (!isAvailable()) return null;
        AABB box = new AABB(pos, pos).inflate(radius);
        Entity best = null;
        double bestD = Double.MAX_VALUE;
        for (Entity e : level.getEntities((Entity) null, box, x -> vehicleCls.isInstance(x) && (filter == null || filter.test(x)))) {
            double d = e.position().distanceToSqr(pos);
            if (d < bestD) { bestD = d; best = e; }
        }
        return best;
    }

    // ── Riding ────────────────────────────────────────────────────────────

    public static int maxPassengers(Entity v) { return (int) call(v, getMaxPassengers, 0); }
    public static int seatIndex(Entity v, Entity who) { return (int) call(v, getSeatIndex, -1, who); }

    @SuppressWarnings("unchecked")
    public static List<Entity> orderedPassengers(Entity v) {
        Object o = call(v, getOrderedPassengers, null);
        return o instanceof List<?> l ? (List<Entity>) l : List.of();
    }

    /** First seat index that is free, or -1. */
    public static int firstFreeSeat(Entity v) {
        int max = maxPassengers(v);
        List<Entity> ps = orderedPassengers(v);
        for (int i = 0; i < max; i++) {
            if (i >= ps.size() || ps.get(i) == null) return i;
        }
        return -1;
    }

    /** Board and (optionally) move to a seat. Returns an error string or null. */
    public static String board(ServerPlayer bot, Entity v, int seat) {
        if (!isVehicle(v)) return "not a vehicle";
        if (isWreck(v)) return "vehicle is wrecked";
        if (bot.getVehicle() == v) {
            if (seat >= 0) call(v, changeSeat, false, bot, seat);
            return null;
        }
        if (bot.isPassenger()) bot.stopRiding();
        if (!bot.startRiding(v, true)) return "could not board (no free seat?)";
        if (seat >= 0 && seatIndex(v, bot) != seat) {
            Object ok = call(v, changeSeat, false, bot, seat);
            if (!(ok instanceof Boolean b && b)) {
                // stay wherever startRiding put us; not fatal
                AIPlayerMod.LOGGER.debug("[SwVehicleCompat] seat {} unavailable, staying in seat {}", seat, seatIndex(v, bot));
            }
        }
        return null;
    }

    public static boolean changeSeat(ServerPlayer bot, int seat) {
        Entity v = vehicleOf(bot);
        return v != null && (boolean) call(v, changeSeat, false, bot, seat);
    }

    public static void dismount(ServerPlayer bot) {
        if (bot.isPassenger()) bot.stopRiding();
    }

    public static boolean isDriver(ServerPlayer bot) {
        Entity v = vehicleOf(bot);
        return v != null && call(v, getFirstPassenger, null) == bot;
    }

    // ── Weapons ───────────────────────────────────────────────────────────

    public static boolean hasWeapon(Entity v, int seat) { return (boolean) call(v, hasWeaponSeat, false, seat); }
    public static boolean canShoot(ServerPlayer bot) {
        Entity v = vehicleOf(bot);
        return v != null && (boolean) call(v, canShoot, false, bot);
    }
    public static void fire(ServerPlayer bot, UUID targetUuid, Vec3 targetPos) {
        Entity v = vehicleOf(bot);
        if (v != null) call(v, vehicleShoot, null, bot, targetUuid, targetPos);
    }
    public static int rpm(ServerPlayer bot) {
        Entity v = vehicleOf(bot);
        return v == null ? -1 : (int) call(v, weaponRpm, -1, bot);
    }
    public static int ammoCount(ServerPlayer bot) {
        Entity v = vehicleOf(bot);
        return v == null ? -1 : (int) call(v, ammoCountLiving, -1, bot);
    }
    public static int selectedWeapon(Entity v, int seat) { return (int) call(v, getSelectedWeaponSeat, -1, seat); }
    public static void changeWeapon(Entity v, int seat, int index) { call(v, changeWeapon, null, seat, index, false); }

    @SuppressWarnings("unchecked")
    public static List<String> weaponNames(Entity v, int seat) {
        try {
            Object data = computed.invoke(v);
            List<?> seats = (List<?>) seatsOf.invoke(data);
            if (seat < 0 || seat >= seats.size()) return List.of();
            Object w = weaponsOf.invoke(seats.get(seat));
            return w instanceof List<?> l ? new ArrayList<>((List<String>) l) : List.of();
        } catch (Exception e) {
            return List.of();
        }
    }

    public static String weaponName(Entity v, int seat) {
        List<String> names = weaponNames(v, seat);
        int idx = selectedWeapon(v, seat);
        return idx >= 0 && idx < names.size() ? names.get(idx) : (names.isEmpty() ? "" : names.get(0));
    }

    /**
     * Item id the bot's current vehicle weapon consumes, or "FE" (energy),
     * "player-ammo", "" (none/unknown).
     */
    public static String ammoItemFor(ServerPlayer bot) {
        Entity v = vehicleOf(bot);
        if (v == null || getGunDataLiving == null) return "";
        try {
            Object data = getGunDataLiving.invoke(v, bot);
            if (data == null) return "";
            Object consumer = dataSelectedConsumer.invoke(data);
            if (consumer == null) return "";
            String type = String.valueOf(consumerGetType.invoke(consumer));
            switch (type) {
                case "ENERGY": return "FE";
                case "PLAYER_AMMO": return "player-ammo";
                case "ITEM": {
                    Object st = consumerStack.invoke(consumer);
                    if (st instanceof ItemStack s && !s.isEmpty()) {
                        return net.minecraft.core.registries.BuiltInRegistries.ITEM.getKey(s.getItem()).toString();
                    }
                    return "";
                }
                default: return "";
            }
        } catch (Exception e) {
            return "";
        }
    }

    // ── Movement ──────────────────────────────────────────────────────────

    public static void setInputs(Entity v, boolean fwd, boolean back, boolean left, boolean right,
                                 boolean up, boolean down, boolean sprint) {
        call(v, setForward, null, fwd);
        call(v, setBack, null, back);
        call(v, setLeft, null, left);
        call(v, setRight, null, right);
        call(v, setUp, null, up);
        call(v, setDown, null, down);
        call(v, setSprint, null, sprint);
    }

    public static void clearInputs(Entity v) { setInputs(v, false, false, false, false, false, false, false); }

    /** Diagnostic snapshot of the drive state (power + raw input flags). */
    public static java.util.Map<String, Object> driveDebug(Entity v) {
        java.util.Map<String, Object> m = new java.util.LinkedHashMap<>();
        m.put("power", call(v, getPower, -1f));
        m.put("forward", call(v, fwdDown, false));
        m.put("back", call(v, backDown, false));
        m.put("left", call(v, leftDown, false));
        m.put("right", call(v, rightDown, false));
        m.put("up", call(v, upDown, false));
        m.put("sprint", call(v, sprintDown, false));
        m.put("yaw", v.getYRot());
        m.put("onGround", v.onGround());
        m.put("engine", engineKind(v).name());
        m.put("tickCount", v.tickCount);
        m.put("gameTime", v.level().getGameTime());
        m.put("motion", v.getDeltaMovement().toString());
        m.put("engineDamaged", call(v, engDamaged, null));
        m.put("lWheelDamaged", call(v, lWheelDamaged, null));
        m.put("rWheelDamaged", call(v, rWheelDamaged, null));
        m.put("turretDamaged", call(v, turretDamaged, null));
        m.put("engineHealth", call(v, engHealth, null) + "/" + call(v, engMax, null));
        m.put("wheelHealth", call(v, lWheelHealth, null) + "/" + call(v, wheelMax, null));
        return m;
    }

    /** Full repair: hull + every part to max. Returns false if unsupported. */
    public static boolean repair(Entity v) {
        if (!isVehicle(v)) return false;
        float hull = maxHealth(v);
        if (hull > 0) call(v, setHealth, null, hull);
        Object em = call(v, engMax, null), wm = call(v, wheelMax, null), tm = call(v, turretMax, null);
        if (em instanceof Float f) { call(v, setEngHealth, null, f); call(v, setSubEngHealth, null, f); }
        if (wm instanceof Float f) { call(v, setLWheel, null, f); call(v, setRWheel, null, f); }
        if (tm instanceof Float f) call(v, setTurretHealth, null, f);
        return true;
    }

    public static void mouseInput(Entity v, double dx, double dy) { call(v, mouseInput, null, dx, dy); }

    public static EngineKind engineKind(Entity v) {
        Object info = call(v, getEngineInfo, null);
        if (info == null) return EngineKind.NONE;
        String n = info.getClass().getSimpleName();
        if (n.contains("Track") || n.contains("Wheel")) return EngineKind.LAND;
        if (n.contains("Ship")) return EngineKind.BOAT;
        if (n.contains("Helicopter")) return EngineKind.HELI;
        if (n.contains("Aircraft") || n.contains("Tom6")) return EngineKind.PLANE;
        return EngineKind.FIXED;
    }

    public static boolean drivable(Entity v) {
        EngineKind k = engineKind(v);
        return k == EngineKind.LAND || k == EngineKind.BOAT || k == EngineKind.HELI;
    }

    // ── Energy / inventory / health ───────────────────────────────────────

    public static int energy(Entity v) { return (int) call(v, getEnergy, 0); }
    public static int maxEnergy(Entity v) { return (int) call(v, getMaxEnergy, 0); }
    public static boolean hasEnergyStorage(Entity v) { return (boolean) call(v, hasEnergyStorage, false); }
    public static void setEnergy(Entity v, int n) { call(v, setEnergy, null, n); }

    /** Insert up to n FE; returns the amount actually accepted. */
    public static int receiveEnergy(Entity v, int n) {
        IEnergyStorage es = v.getCapability(Capabilities.EnergyStorage.ENTITY, null);
        if (es != null) return es.receiveEnergy(n, false);
        int cur = energy(v), max = maxEnergy(v);
        int add = Math.max(0, Math.min(n, max - cur));
        if (add > 0) setEnergy(v, cur + add);
        return add;
    }

    public static IItemHandler inventory(Entity v) {
        return v.getCapability(Capabilities.ItemHandler.ENTITY, null);
    }
    public static int containerSize(Entity v) { return (int) call(v, getContainerSize, 0); }
    public static boolean hasContainer(Entity v) { return (boolean) call(v, hasContainer, false); }

    public static float health(Entity v) { return (float) call(v, getHealth, 0f); }
    public static float maxHealth(Entity v) { return (float) call(v, getMaxHealth, 0f); }
    public static void heal(Entity v, float amount) { call(v, heal, null, amount); }
    public static boolean isWreck(Entity v) { return (boolean) call(v, isWreck, false); }

    public static String typeName(Entity v) {
        Object t = call(v, getVehicleType, null);
        return t == null ? "" : t.toString();
    }

    public static String displayName(Entity v) {
        return v.getDisplayName().getString();
    }

    // ── plumbing ──────────────────────────────────────────────────────────

    private static Object call(Entity v, Method m, Object def, Object... args) {
        if (v == null || m == null || !isVehicle(v)) return def;
        try {
            Object r = m.invoke(v, args);
            return r == null ? def : r;
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[SwVehicleCompat] {} failed: {}", m.getName(), e.toString());
            return def;
        }
    }

    private static boolean resolve() {
        Boolean r = resolved;
        if (r != null) return r;
        synchronized (SwVehicleCompat.class) {
            if (resolved != null) return resolved;
            try {
                vehicleCls = Class.forName("com.atsuishio.superbwarfare.entity.vehicle.base.VehicleEntity");
                getFirstPassenger = vehicleCls.getMethod("getFirstPassenger");
                getOrderedPassengers = vehicleCls.getMethod("getOrderedPassengers");
                changeSeat = vehicleCls.getMethod("changeSeat", Entity.class, int.class);
                getSeatIndex = vehicleCls.getMethod("getSeatIndex", Entity.class);
                getMaxPassengers = vehicleCls.getMethod("getMaxPassengers");
                hasWeaponSeat = vehicleCls.getMethod("hasWeapon", int.class);
                changeWeapon = vehicleCls.getMethod("changeWeapon", int.class, int.class, boolean.class);
                getSelectedWeaponSeat = vehicleCls.getMethod("getSelectedWeapon", int.class);
                canShoot = vehicleCls.getMethod("canShoot", LivingEntity.class);
                vehicleShoot = vehicleCls.getMethod("vehicleShoot", LivingEntity.class, UUID.class, Vec3.class);
                weaponRpm = vehicleCls.getMethod("vehicleWeaponRpm", LivingEntity.class);
                ammoCountLiving = vehicleCls.getMethod("getAmmoCount", LivingEntity.class);
                setForward = vehicleCls.getMethod("setForwardInputDown", boolean.class);
                setBack = vehicleCls.getMethod("setBackInputDown", boolean.class);
                setLeft = vehicleCls.getMethod("setLeftInputDown", boolean.class);
                setRight = vehicleCls.getMethod("setRightInputDown", boolean.class);
                setUp = vehicleCls.getMethod("setUpInputDown", boolean.class);
                setDown = vehicleCls.getMethod("setDownInputDown", boolean.class);
                setSprint = vehicleCls.getMethod("setSprintInputDown", boolean.class);
                mouseInput = vehicleCls.getMethod("mouseInput", double.class, double.class);
                getEnergy = vehicleCls.getMethod("getEnergy");
                getMaxEnergy = vehicleCls.getMethod("getMaxEnergy");
                setEnergy = vehicleCls.getMethod("setEnergy", int.class);
                hasEnergyStorage = vehicleCls.getMethod("hasEnergyStorage");
                getContainerSize = vehicleCls.getMethod("getContainerSize");
                hasContainer = vehicleCls.getMethod("hasContainer");
                getHealth = vehicleCls.getMethod("getHealth");
                getMaxHealth = vehicleCls.getMethod("getMaxHealth");
                heal = vehicleCls.getMethod("heal", float.class);
                getVehicleType = vehicleCls.getMethod("getVehicleType");
                getEngineInfo = vehicleCls.getMethod("getEngineInfo");
                isWreck = vehicleCls.getMethod("isWreck");
                computed = vehicleCls.getMethod("computed");
                try {
                    getPower = vehicleCls.getMethod("getPower");
                    fwdDown = vehicleCls.getMethod("forwardInputDown");
                    backDown = vehicleCls.getMethod("backInputDown");
                    leftDown = vehicleCls.getMethod("leftInputDown");
                    rightDown = vehicleCls.getMethod("rightInputDown");
                    upDown = vehicleCls.getMethod("upInputDown");
                    sprintDown = vehicleCls.getMethod("sprintInputDown");
                } catch (Throwable ignored) {
                }
                try {
                    engDamaged = vehicleCls.getMethod("getMainEngineDamaged");
                    lWheelDamaged = vehicleCls.getMethod("getLeftWheelDamaged");
                    rWheelDamaged = vehicleCls.getMethod("getRightWheelDamaged");
                    turretDamaged = vehicleCls.getMethod("getTurretDamaged");
                    engHealth = vehicleCls.getMethod("getMainEngineHealth");
                    engMax = vehicleCls.getMethod("getEngineMaxHealth");
                    lWheelHealth = vehicleCls.getMethod("getLeftWheelHealth");
                    wheelMax = vehicleCls.getMethod("getWheelMaxHealth");
                    turretMax = vehicleCls.getMethod("getTurretMaxHealth");
                    setEngHealth = vehicleCls.getMethod("setMainEngineHealth", float.class);
                    setSubEngHealth = vehicleCls.getMethod("setSubEngineHealth", float.class);
                    setLWheel = vehicleCls.getMethod("setLeftWheelHealth", float.class);
                    setRWheel = vehicleCls.getMethod("setRightWheelHealth", float.class);
                    setTurretHealth = vehicleCls.getMethod("setTurretHealth", float.class);
                    setHealth = vehicleCls.getMethod("setHealth", float.class);
                } catch (Throwable ignored) {
                }
                Class<?> dataCls = Class.forName("com.atsuishio.superbwarfare.data.vehicle.DefaultVehicleData");
                seatsOf = dataCls.getMethod("seats");
                Class<?> seatCls = Class.forName("com.atsuishio.superbwarfare.data.vehicle.subdata.SeatInfo");
                weaponsOf = seatCls.getMethod("weapons");
                try {
                    getGunDataLiving = vehicleCls.getMethod("getGunData", Entity.class);
                    Class<?> gunData = Class.forName("com.atsuishio.superbwarfare.data.gun.GunData");
                    dataSelectedConsumer = gunData.getMethod("selectedAmmoConsumer");
                    Class<?> consumer = Class.forName("com.atsuishio.superbwarfare.data.gun.AmmoConsumer");
                    consumerStack = consumer.getMethod("stack");
                    consumerGetType = consumer.getMethod("getType");
                    consumerGetPlayerAmmoType = consumer.getMethod("getPlayerAmmoType");
                } catch (Throwable t) {
                    getGunDataLiving = null;
                }
                resolved = true;
                AIPlayerMod.LOGGER.info("[SwVehicleCompat] Superb Warfare vehicles wired for bots");
            } catch (Throwable t) {
                resolved = false;
                AIPlayerMod.LOGGER.warn("[SwVehicleCompat] Superb Warfare vehicle API not resolvable ({}); vehicle features off", t.toString());
            }
            return resolved;
        }
    }
}
