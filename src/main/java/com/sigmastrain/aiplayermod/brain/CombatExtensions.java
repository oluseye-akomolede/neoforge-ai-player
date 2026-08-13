package com.sigmastrain.aiplayermod.brain;

import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.LivingEntity;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Extension seam: other mods teach bots to fight with gear this mod knows
 * nothing about. Hive uses it so a unit carrying Modular Golems armament
 * actually FIRES it — MG's own weapon logic is bound to golem entities
 * and never runs for a player-shaped bot, so the effect has to be
 * executed here.
 *
 * <p>Handlers are polled every combat tick, before the melee swing.
 */
public final class CombatExtensions {

    private CombatExtensions() {}

    public interface CombatHandler {
        /**
         * @param distance current distance to the target
         * @return cooldown ticks to wait before the next attack attempt,
         * or -1 when this handler did nothing (fall through to melee).
         */
        int tryAttack(ServerPlayer bot, LivingEntity target, double distance);
    }

    private static final List<CombatHandler> HANDLERS = new ArrayList<>();

    public static synchronized void register(CombatHandler h) {
        HANDLERS.add(h);
    }

    public static synchronized List<CombatHandler> handlers() {
        return Collections.unmodifiableList(new ArrayList<>(HANDLERS));
    }

    /** @return cooldown ticks if a handler acted, else -1. */
    public static int tryAll(ServerPlayer bot, LivingEntity target, double distance) {
        for (CombatHandler h : handlers()) {
            try {
                int cd = h.tryAttack(bot, target, distance);
                if (cd >= 0) return cd;
            } catch (Throwable ignored) {
            }
        }
        return -1;
    }
}
