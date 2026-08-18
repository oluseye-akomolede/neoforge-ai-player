package com.sigmastrain.aiplayermod.compat.guns;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.CombatExtensions;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.item.ItemStack;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Makes bots fight with TaCZ and Superb Warfare hand guns. Registered as a
 * {@link CombatExtensions.CombatHandler} so every combat path (directive
 * combat, combat mode, attack action) polls it before swinging.
 *
 * <p>Per bot it remembers which gun stack it last drew (TaCZ needs an explicit
 * draw, like a client's hand-change packet) and when a gun went dry, so an
 * empty gun is skipped for a while instead of blocking melee forever.
 */
public final class GunHandler implements CombatExtensions.CombatHandler {

    /** Standoff distance guns are engaged from. */
    public static final double GUN_RANGE = 40.0;
    private static final int DRY_TICKS = 200;          // re-check ammo every 10 s
    private static final int DEFAULT_INTERVAL = 4;     // ticks between shots when rpm unknown

    private static final Map<UUID, ItemStack> DRAWN = new ConcurrentHashMap<>();
    private static final Map<UUID, Long> DRY_UNTIL = new ConcurrentHashMap<>();
    private static final Map<UUID, String> ANNOUNCED = new ConcurrentHashMap<>();
    private static final Map<UUID, Integer> NO_AMMO_STREAK = new ConcurrentHashMap<>();

    private static boolean registered;

    public static synchronized void register() {
        if (registered) return;
        if (!TaczCompat.isAvailable() && !SwGunCompat.isAvailable()) {
            AIPlayerMod.LOGGER.info("[GunHandler] no supported gun mod loaded; handler idle");
        }
        CombatExtensions.register(new GunHandler());
        registered = true;
        AIPlayerMod.LOGGER.info("[GunHandler] gun combat handler registered (tacz={}, superbwarfare={})",
                TaczCompat.isAvailable(), SwGunCompat.isAvailable());
    }

    public static boolean isGun(ItemStack stack) {
        return TaczCompat.isGun(stack) || SwGunCompat.isGun(stack);
    }

    /** True while the gun is fireable now, or could be after a reload attempt. */
    private static boolean usable(ServerPlayer bot, ItemStack gun) {
        if (SwGunCompat.isGun(gun)) {
            // hasAmmo covers loaded + backpack ammo; a dry SW gun is retried after DRY_TICKS.
            return SwGunCompat.hasAmmo(bot, gun) || SwGunCompat.reloading(gun) || !dry(bot);
        }
        // TaCZ: no cheap ammo query — trust it until a shot reports NO_AMMO after a reload.
        return TaczCompat.isGun(gun);
    }

    private static boolean dry(ServerPlayer bot) {
        Long until = DRY_UNTIL.get(bot.getUUID());
        return until != null && bot.level().getGameTime() < until;
    }

    private static void markDry(ServerPlayer bot) {
        DRY_UNTIL.put(bot.getUUID(), bot.level().getGameTime() + DRY_TICKS);
    }

    @Override
    public double preferredRange(ServerPlayer bot) {
        ItemStack held = bot.getMainHandItem();
        return isGun(held) && !dry(bot) ? GUN_RANGE : -1;
    }

    @Override
    public int preferredWeaponSlot(ServerPlayer bot) {
        if (dry(bot)) return -1;
        var inv = bot.getInventory();
        for (int i = 0; i < 36; i++) {
            ItemStack s = inv.getItem(i);
            if (isGun(s) && usable(bot, s)) return i;
        }
        return -1;
    }

    @Override
    public int tryAttack(ServerPlayer bot, LivingEntity target, double distance) {
        ItemStack gun = bot.getMainHandItem();
        if (!isGun(gun) || dry(bot)) return -1;
        if (distance > GUN_RANGE) return -1;

        BotPlayer bp = BotManager.getBot(bot.getGameProfile().getName());
        String targetName = target.getName().getString();
        String key = gun.getHoverName().getString() + "@" + target.getId();
        if (!key.equals(ANNOUNCED.get(bot.getUUID()))) {
            ANNOUNCED.put(bot.getUUID(), key);
            if (bp != null) bp.systemChat("Firing " + gun.getHoverName().getString() + " at " + targetName, "yellow");
        }

        // Don't shoot a player, or through one standing between the bot and the target.
        if (target instanceof ServerPlayer) return -1;
        if (bot.level() instanceof net.minecraft.server.level.ServerLevel sl) {
            net.minecraft.world.phys.Vec3 aim = target.position().add(0, target.getBbHeight() * 0.5, 0);
            if (com.sigmastrain.aiplayermod.brain.CombatSafety.firingEndangersPlayer(sl, bot.getEyePosition(), aim, 0.0, 1.5)) {
                return 8; // hold; re-check shortly
            }
        }

        if (TaczCompat.isGun(gun)) return fireTacz(bot, bp, gun);
        return fireSw(bot, bp, gun);
    }

    private int fireTacz(ServerPlayer bot, BotPlayer bp, ItemStack gun) {
        ItemStack drawn = DRAWN.get(bot.getUUID());
        if (drawn == null || drawn != gun) {
            TaczCompat.draw(bot);
            DRAWN.put(bot.getUUID(), gun);
            return 10; // draw time
        }
        String r = TaczCompat.shoot(bot);
        if (!"NO_AMMO".equals(r)) NO_AMMO_STREAK.remove(bot.getUUID());
        switch (r) {
            case "SUCCESS":       return DEFAULT_INTERVAL;
            case "COOL_DOWN":     return 1;
            case "IS_DRAWING":
            case "IS_RELOADING":
            case "IS_BOLTING":    return 5;
            case "NEED_BOLT":     TaczCompat.bolt(bot); return 8;
            case "NOT_DRAW":      TaczCompat.draw(bot); return 10;
            case "NO_AMMO": {
                // First miss: reload (pulls ammo items from the bot's inventory)
                // and wait for it. Second consecutive miss: the gun is dry.
                int streak = NO_AMMO_STREAK.merge(bot.getUUID(), 1, Integer::sum);
                if (streak == 1) {
                    TaczCompat.reload(bot);
                    return 40;
                }
                NO_AMMO_STREAK.remove(bot.getUUID());
                markDry(bot);
                if (bp != null) bp.systemChat("Out of ammo for " + gun.getHoverName().getString(), "red");
                return -1;
            }
            default:
                // Unknown/failed result — don't stall combat on this gun.
                markDry(bot);
                return -1;
        }
    }

    private int fireSw(ServerPlayer bot, BotPlayer bp, ItemStack gun) {
        if (SwGunCompat.canShoot(bot, gun)) {
            SwGunCompat.shoot(bot, gun);
            int rpm = SwGunCompat.rpm(gun);
            return rpm > 0 ? Math.max(1, Math.round(1200f / rpm)) : DEFAULT_INTERVAL;
        }
        if (SwGunCompat.reloading(gun)) return 5;
        // Not shootable: try to feed player-ammo, then start a reload.
        boolean fed = SwGunCompat.feedPlayerAmmo(bot, gun);
        SwGunCompat.tryReload(bot, gun);
        if (SwGunCompat.reloading(gun) || fed) return 10;
        if (!SwGunCompat.hasAmmo(bot, gun)) {
            markDry(bot);
            if (bp != null) bp.systemChat("Out of ammo for " + gun.getHoverName().getString(), "red");
            return -1;
        }
        return 5;
    }
}
