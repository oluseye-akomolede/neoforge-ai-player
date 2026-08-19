package com.sigmastrain.aiplayermod.brain;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Live, per-bot control knobs for a running fusion — the mechanism that lets L3
 * commands change the behavior of the continuously-running MANAGE_FUSION
 * directive <em>in realtime without cancelling it</em>. The manage behavior
 * re-reads these every tick; the {@code manage_fusion} API writes them.
 */
public final class FusionControl {

    private FusionControl() {}

    /** Mutable knobs (not a record — fields are set live). */
    public static final class Knobs {
        /** Reactor: target activity 0..1 (fraction of max burn / drain). */
        public volatile double targetRate = 0.5;
        /** Reactor: keep it inside safe temperature/shield margins (auto-scram on danger). */
        public volatile boolean safeMode = true;
        /** Storage-output mode: FE/tick to push from the reservoir into the block. */
        public volatile long outputRate = 0;
        /** Whether the fused generator/reactor diverts its output into cultivation. */
        public volatile boolean divert = true;
    }

    private static final Map<String, Knobs> KNOBS = new ConcurrentHashMap<>();

    public static Knobs get(String bot) {
        return KNOBS.computeIfAbsent(bot, b -> new Knobs());
    }

    public static void clear(String bot) {
        KNOBS.remove(bot);
    }

    public static Map<String, Object> toMap(String bot) {
        Knobs k = KNOBS.get(bot);
        if (k == null) return Map.of();
        return Map.of("target_rate", k.targetRate, "safe_mode", k.safeMode,
                "output_rate", k.outputRate, "divert", k.divert);
    }
}
