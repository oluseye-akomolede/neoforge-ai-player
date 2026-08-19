package com.sigmastrain.aiplayermod.brain;

import com.sigmastrain.aiplayermod.compat.blockfusion.BlockFusionCompat.Role;
import net.minecraft.core.BlockPos;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The live binding of a bot to a block it has fused with — the block analogue of
 * riding a vehicle. A side-channel registry (like {@code Requisitions}): the
 * fusion behavior writes it, hive's {@code BlockFusionEngine} reads it to move
 * FE. Nothing here touches the economy.
 */
public final class Fusion {

    private Fusion() {}

    /** Storage-fusion sub-mode: add the block's capacity to the FE cap, or push FE into it. */
    public enum Mode { CAPACITY, OUTPUT }

    public record State(String bot, String dimension, BlockPos pos, Role role, Mode mode) {
        public Map<String, Object> toMap() {
            return Map.of("bot", bot, "dimension", dimension,
                    "x", pos.getX(), "y", pos.getY(), "z", pos.getZ(),
                    "role", role.name(), "mode", mode.name());
        }
    }

    private static final Map<String, State> FUSED = new ConcurrentHashMap<>();

    public static void fuse(String bot, String dimension, BlockPos pos, Role role, Mode mode) {
        FUSED.put(bot, new State(bot, dimension, pos.immutable(), role, mode));
    }

    public static void setMode(String bot, Mode mode) {
        State s = FUSED.get(bot);
        if (s != null) FUSED.put(bot, new State(s.bot(), s.dimension(), s.pos(), s.role(), mode));
    }

    public static void unfuse(String bot) {
        FUSED.remove(bot);
    }

    public static State of(String bot) {
        return FUSED.get(bot);
    }

    public static boolean isFused(String bot) {
        return FUSED.containsKey(bot);
    }

    public static List<State> all() {
        return new ArrayList<>(FUSED.values());
    }
}
