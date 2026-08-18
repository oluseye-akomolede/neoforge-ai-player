package com.sigmastrain.aiplayermod.brain;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.bot.VehicleDriver;
import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec3;

/**
 * Movement while aboard a Superb Warfare vehicle. Movement behaviors (FOLLOW,
 * GOTO) call {@link #steer} first: a bot that is riding must never
 * {@code moveTo}/teleport itself — the vehicle's positionRider overwrites that
 * every tick, which is why a mounted unit looked frozen. A driver drives the
 * vehicle toward the goal; a passenger just rides.
 *
 * @return true if the bot is aboard (the caller must not move the bot itself)
 */
public final class VehicleRide {

    private VehicleRide() {}

    public static boolean steer(BotPlayer bot, ServerPlayer player, VehicleDriver.State st, Vec3 goal, double arrive) {
        Entity v = SwVehicleCompat.vehicleOf(player);
        if (v == null) return false;
        if (goal != null && SwVehicleCompat.isDriver(player) && SwVehicleCompat.drivable(v)) {
            boolean noEnergy = SwVehicleCompat.hasEnergyStorage(v) && SwVehicleCompat.energy(v) <= 0;
            if (noEnergy) { VehicleDriver.stop(v); return true; }
            VehicleDriver.driveTo(v, st, goal, Math.max(arrive, VehicleDriver.DEFAULT_ARRIVE));
        }
        return true;
    }

    public static void release(ServerPlayer player) {
        Entity v = SwVehicleCompat.vehicleOf(player);
        if (v != null && SwVehicleCompat.isDriver(player)) VehicleDriver.stop(v);
    }
}
