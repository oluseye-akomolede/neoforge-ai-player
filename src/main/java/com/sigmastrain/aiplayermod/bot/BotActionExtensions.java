package com.sigmastrain.aiplayermod.bot;

import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Extension seam: other mods contribute per-bot buttons to the overlay's unit
 * panel without owning a whole tab. hive-mod uses it for "⚡ Charge (FE)" and
 * "⚙ Materialize ammo (FE)" on a unit aboard a vehicle.
 *
 * <p>Labels ride the fleet snapshot per bot (only actions whose
 * {@link BotAction#visible} says so); a click comes back as
 * {@code VehicleOp(bot, "ext", id)} and {@link BotAction#run} executes on the
 * server thread, returning a one-line result shown as a ControlAck.
 */
public final class BotActionExtensions {

    private BotActionExtensions() {}

    public interface BotAction {
        /** Stable id (e.g. "hive:charge"). */
        String id();
        /** Button label. */
        String label();
        /** Should the button show for this bot right now? (snapshot is fleet-wide, not per viewer) */
        boolean visible(BotPlayer bot);
        /** Do it. Return a short human message (ok or error). */
        String run(ServerPlayer viewer, BotPlayer bot);
    }

    private static final List<BotAction> ACTIONS = new ArrayList<>();

    public static synchronized void register(BotAction a) {
        ACTIONS.removeIf(x -> x.id().equals(a.id()));
        ACTIONS.add(a);
    }

    public static synchronized List<BotAction> all() {
        return Collections.unmodifiableList(new ArrayList<>(ACTIONS));
    }

    public static BotAction find(String id) {
        for (BotAction a : all()) if (a.id().equals(id)) return a;
        return null;
    }
}
