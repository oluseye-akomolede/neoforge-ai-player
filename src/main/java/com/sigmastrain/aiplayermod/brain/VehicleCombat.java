package com.sigmastrain.aiplayermod.brain;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.bot.VehicleDriver;
import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.phys.Vec3;

import java.util.List;

/**
 * Combat while aboard a Superb Warfare vehicle — shared by directive combat and
 * combat mode. The bot never teleports while aboard: a gunner seat aims (the
 * turret follows the seated bot's view) and fires at the weapon's cadence,
 * switching to another weapon of the seat when the current one runs dry; a
 * driver of a drivable vehicle closes to weapon range first (land/boat/heli),
 * everyone else holds position and shoots what comes in range.
 */
public final class VehicleCombat {

    private VehicleCombat() {}

    public static final class State {
        final VehicleDriver.State drive = new VehicleDriver.State();
        int fireCd;
        int switchCd;
        int announcedTarget = -1;
        boolean dryAnnounced;
    }

    /** Engagement range by weapon name — SW weapon names are free-form strings. */
    static double rangeFor(String weapon) {
        String w = weapon == null ? "" : weapon.toLowerCase();
        if (w.contains("missile") || w.contains("rocket") || w.contains("bomb") || w.contains("cannon")
                || w.contains("main") || w.contains("laser") || w.contains("artillery")) return 64;
        if (w.contains("gun") || w.contains("mg")) return 48;
        return 32;
    }

    /**
     * Run one aboard-combat tick. Returns false if the bot isn't aboard an SW
     * vehicle (caller proceeds with normal combat), true if handled.
     */
    public static boolean tick(BotPlayer bot, ServerPlayer player, Entity target, State st) {
        Entity v = SwVehicleCompat.vehicleOf(player);
        if (v == null) return false;
        if (st.fireCd > 0) st.fireCd--;
        if (st.switchCd > 0) st.switchCd--;

        int seat = SwVehicleCompat.seatIndex(v, player);
        boolean armed = SwVehicleCompat.hasWeapon(v, seat);
        String weapon = armed ? SwVehicleCompat.weaponName(v, seat) : "";
        double range = armed ? rangeFor(weapon) : -1;
        double dist = player.distanceTo(target);
        String vName = SwVehicleCompat.displayName(v);

        if (st.announcedTarget != target.getId()) {
            st.announcedTarget = target.getId();
            st.dryAnnounced = false;
            bot.systemChat("Engaging " + target.getName().getString() + " from " + vName
                    + (armed ? " (" + weapon + ")" : " (unarmed seat)"), "yellow");
        }

        // Aim: the seated occupant's view drives the turret.
        Vec3 aim = target.position().add(0, target.getBbHeight() * 0.5, 0);
        bot.lookAt(aim.x, aim.y, aim.z);

        // Never fire on a player, and never when a player would be caught in the
        // blast or the line of fire (a vehicle cannon killed its owner this way).
        boolean friendlyTarget = target instanceof ServerPlayer;
        double blast = com.sigmastrain.aiplayermod.brain.CombatSafety.blastFor(weapon);
        boolean endangers = player.level() instanceof net.minecraft.server.level.ServerLevel sl
                && com.sigmastrain.aiplayermod.brain.CombatSafety.firingEndangersPlayer(
                        sl, player.getEyePosition(), aim, blast, 2.0);

        // Fire.
        if (armed && dist <= range && st.fireCd <= 0 && target instanceof LivingEntity && !friendlyTarget && !endangers) {
            if (SwVehicleCompat.canShoot(player)) {
                SwVehicleCompat.fire(player, target.getUUID(), aim);
                int rpm = SwVehicleCompat.rpm(player);
                st.fireCd = rpm > 0 ? Math.max(1, Math.round(1200f / rpm)) : 10;
                st.dryAnnounced = false;
            } else if (SwVehicleCompat.ammoCount(player) <= 0) {
                // Try the seat's other weapons before declaring the seat dry.
                List<String> names = SwVehicleCompat.weaponNames(v, seat);
                if (names.size() > 1 && st.switchCd <= 0) {
                    int cur = SwVehicleCompat.selectedWeapon(v, seat);
                    SwVehicleCompat.changeWeapon(v, seat, (Math.max(cur, 0) + 1) % names.size());
                    st.switchCd = 40;
                } else if (!st.dryAnnounced) {
                    st.dryAnnounced = true;
                    bot.systemChat(vName + " " + weapon + " is out of ammo", "red");
                }
                st.fireCd = 20;
            } else {
                st.fireCd = 5; // reloading / heat / charging
            }
        } else if (armed && dist <= range && (friendlyTarget || endangers) && st.fireCd <= 0) {
            if (!st.dryAnnounced) {   // reuse the throttle flag to avoid spam
                bot.systemChat("Holding fire — friendly in the line", "yellow");
            }
            st.fireCd = 10;
        }

        // Move: only the driver of a drivable vehicle closes distance.
        if (SwVehicleCompat.isDriver(player) && SwVehicleCompat.drivable(v)) {
            double closeTo = armed ? range * 0.6 : 6.0;
            if (dist > closeTo && !(SwVehicleCompat.hasEnergyStorage(v) && SwVehicleCompat.energy(v) <= 0)) {
                VehicleDriver.driveTo(v, st.drive, target.position(), closeTo);
            } else {
                VehicleDriver.stop(v);
            }
        }
        return true;
    }

    /** Release controls when combat ends while still aboard. */
    public static void release(ServerPlayer player) {
        Entity v = SwVehicleCompat.vehicleOf(player);
        if (v != null && SwVehicleCompat.isDriver(player)) VehicleDriver.stop(v);
    }
}
