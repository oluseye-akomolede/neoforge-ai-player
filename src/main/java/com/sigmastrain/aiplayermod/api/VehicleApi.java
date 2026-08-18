package com.sigmastrain.aiplayermod.api;

import com.google.gson.JsonObject;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.DirectiveType;
import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.neoforged.neoforge.items.IItemHandler;
import net.neoforged.neoforge.items.ItemHandlerHelper;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Server-thread implementations of the {@code /bot/{name}/vehicle_*} actions
 * and the vehicle inventory endpoint. Also reused by the overlay's VehicleOp
 * handler so the UI and the API do exactly the same thing.
 */
public final class VehicleApi {

    private VehicleApi() {}

    private static Map<String, Object> err(String msg) {
        return Map.of("ok", false, "error", msg);
    }

    private static String str(JsonObject body, String key, String def) {
        return body != null && body.has(key) && !body.get(key).isJsonNull() ? body.get(key).getAsString() : def;
    }

    private static int num(JsonObject body, String key, int def) {
        try {
            return body != null && body.has(key) ? body.get(key).getAsInt() : def;
        } catch (Exception e) {
            return def;
        }
    }

    public static Map<String, Object> act(BotPlayer bot, String action, JsonObject body) {
        if (!SwVehicleCompat.isAvailable()) return err("Superb Warfare not loaded");
        ServerPlayer p = bot.getPlayer();
        switch (action) {
            case "vehicle_mount" -> {
                // Route through the directive so it shows in the overlay/progress like any other order.
                String target = str(body, "target", "");
                int seat = num(body, "seat", -1);
                String role = str(body, "role", "");
                var b = Directive.builder(DirectiveType.MOUNT_VEHICLE).target(target);
                if (seat >= 0) b.extra("seat", String.valueOf(seat));
                if (!role.isEmpty()) b.extra("role", role);
                int radius = num(body, "radius", -1);
                if (radius > 0) b.radius(radius);
                bot.getBrain().setDirective(b.build());
                return Map.of("ok", true, "queued", "MOUNT_VEHICLE", "target", target);
            }
            case "vehicle_dismount" -> {
                Entity v = SwVehicleCompat.vehicleOf(p);
                if (v == null && !p.isPassenger()) return err("not aboard anything");
                if (v != null) SwVehicleCompat.clearInputs(v);
                SwVehicleCompat.dismount(p);
                return Map.of("ok", true);
            }
            case "vehicle_seat" -> {
                Entity v = SwVehicleCompat.vehicleOf(p);
                if (v == null) return err("not aboard a vehicle");
                int seat = num(body, "seat", -1);
                if (seat < 0) { // next free seat after the current one
                    int cur = SwVehicleCompat.seatIndex(v, p), max = SwVehicleCompat.maxPassengers(v);
                    var ps = SwVehicleCompat.orderedPassengers(v);
                    for (int i = 1; i <= max; i++) {
                        int cand = (cur + i) % max;
                        if (cand >= ps.size() || ps.get(cand) == null) { seat = cand; break; }
                    }
                    if (seat < 0) return err("no other free seat");
                }
                boolean ok = SwVehicleCompat.changeSeat(p, seat);
                return ok ? Map.of("ok", true, "seat", seat) : err("seat " + seat + " unavailable");
            }
            case "vehicle_weapon" -> {
                Entity v = SwVehicleCompat.vehicleOf(p);
                if (v == null) return err("not aboard a vehicle");
                int seat = SwVehicleCompat.seatIndex(v, p);
                List<String> names = SwVehicleCompat.weaponNames(v, seat);
                if (names.isEmpty()) return err("this seat has no weapons");
                int idx = num(body, "index", -1);
                if (idx < 0) idx = (Math.max(SwVehicleCompat.selectedWeapon(v, seat), 0) + 1) % names.size();
                if (idx >= names.size()) return err("weapon index out of range (0-" + (names.size() - 1) + ")");
                SwVehicleCompat.changeWeapon(v, seat, idx);
                return Map.of("ok", true, "weapon", names.get(idx), "index", idx);
            }
            case "vehicle_input" -> {
                // Diagnostic: set the raw input flags once (they persist as entity data).
                Entity v = SwVehicleCompat.vehicleOf(p);
                if (v == null) return err("not aboard a vehicle");
                SwVehicleCompat.setInputs(v,
                        body.has("forward") && body.get("forward").getAsBoolean(),
                        body.has("back") && body.get("back").getAsBoolean(),
                        body.has("left") && body.get("left").getAsBoolean(),
                        body.has("right") && body.get("right").getAsBoolean(),
                        body.has("up") && body.get("up").getAsBoolean(),
                        body.has("down") && body.get("down").getAsBoolean(),
                        body.has("sprint") && body.get("sprint").getAsBoolean());
                return Map.of("ok", true, "debug", SwVehicleCompat.driveDebug(v));
            }
            case "vehicle_repair" -> {
                Entity v = SwVehicleCompat.vehicleOf(p);
                if (v == null) v = SwVehicleCompat.nearestVehicle(p.serverLevel(), p.position(), 4.0, null);
                if (v == null) return err("no vehicle aboard or within 4 blocks");
                boolean ok = SwVehicleCompat.repair(v);
                return Map.of("ok", ok, "health", SwVehicleCompat.health(v), "debug", SwVehicleCompat.driveDebug(v));
            }
            case "vehicle_charge" -> {
                // Raw energy set — the FE-paid path lives in hive-mod. Kept for testing/ops.
                Entity v = SwVehicleCompat.vehicleOf(p);
                if (v == null) v = SwVehicleCompat.nearestVehicle(p.serverLevel(), p.position(), 4.0, null);
                if (v == null) return err("no vehicle aboard or within 4 blocks");
                int amount = num(body, "amount", Integer.MAX_VALUE);
                int accepted = SwVehicleCompat.receiveEnergy(v, amount);
                return Map.of("ok", true, "accepted", accepted,
                        "energy", SwVehicleCompat.energy(v), "max_energy", SwVehicleCompat.maxEnergy(v));
            }
            default -> { return err("unknown vehicle action " + action); }
        }
    }

    /** GET → list; POST {action: insert|extract, slot?, item, count} */
    public static Map<String, Object> inventory(BotPlayer bot, JsonObject body) {
        if (!SwVehicleCompat.isAvailable()) return err("Superb Warfare not loaded");
        ServerPlayer p = bot.getPlayer();
        Entity v = SwVehicleCompat.vehicleOf(p);
        if (v == null) v = SwVehicleCompat.nearestVehicle(p.serverLevel(), p.position(), 4.0, null);
        if (v == null) return err("no vehicle aboard or within 4 blocks");
        IItemHandler h = SwVehicleCompat.inventory(v);
        if (h == null) return err(SwVehicleCompat.displayName(v) + " has no inventory");

        if (body != null && body.has("action")) {
            String a = str(body, "action", "");
            String itemId = str(body, "item", "");
            int count = num(body, "count", 1);
            int slot = num(body, "slot", -1);
            if (a.equals("insert")) {
                // From the bot's carried inventory (then vault) into the vehicle.
                int moved = 0;
                var inv = p.getInventory();
                for (int i = 0; i < inv.getContainerSize() && moved < count; i++) {
                    ItemStack s = inv.getItem(i);
                    if (s.isEmpty() || !idOf(s).equals(itemId)) continue;
                    ItemStack take = s.copyWithCount(Math.min(s.getCount(), count - moved));
                    ItemStack left = slot >= 0 ? h.insertItem(slot, take, false) : ItemHandlerHelper.insertItemStacked(h, take, false);
                    int put = take.getCount() - left.getCount();
                    s.shrink(put);
                    moved += put;
                }
                if (moved < count) {
                    for (ItemStack pulled : bot.getVault().withdraw(itemId, count - moved)) {
                        ItemStack left = slot >= 0 ? h.insertItem(slot, pulled, false) : ItemHandlerHelper.insertItemStacked(h, pulled, false);
                        moved += pulled.getCount() - left.getCount();
                        if (!left.isEmpty()) bot.getVault().deposit(left);
                    }
                }
                return Map.of("ok", true, "moved", moved, "item", itemId);
            }
            if (a.equals("extract")) {
                int moved = 0;
                for (int i = 0; i < h.getSlots() && moved < count; i++) {
                    if (slot >= 0 && i != slot) continue;
                    ItemStack s = h.getStackInSlot(i);
                    if (s.isEmpty() || (!itemId.isEmpty() && !idOf(s).equals(itemId))) continue;
                    ItemStack out = h.extractItem(i, Math.min(s.getCount(), count - moved), false);
                    moved += out.getCount();
                    bot.deliver(out);
                }
                return Map.of("ok", true, "moved", moved);
            }
            return err("action must be insert or extract");
        }

        List<Map<String, Object>> rows = new ArrayList<>();
        for (int i = 0; i < h.getSlots(); i++) {
            ItemStack s = h.getStackInSlot(i);
            if (s.isEmpty()) continue;
            rows.add(Map.of("slot", i, "item", idOf(s), "name", s.getHoverName().getString(), "count", s.getCount()));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("vehicle", SwVehicleCompat.displayName(v));
        out.put("slots", h.getSlots());
        out.put("items", rows);
        return out;
    }

    private static String idOf(ItemStack s) {
        return BuiltInRegistries.ITEM.getKey(s.getItem()).toString();
    }

    /** Resolve an item id leniently (namespace optional). */
    public static Item resolveItem(String id) {
        if (id == null || id.isEmpty()) return Items.AIR;
        ResourceLocation rl = ResourceLocation.tryParse(id.contains(":") ? id : "minecraft:" + id);
        return rl == null ? Items.AIR : BuiltInRegistries.ITEM.get(rl);
    }
}
