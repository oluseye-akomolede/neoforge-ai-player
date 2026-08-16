package com.sigmastrain.aiplayermod.compat;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.neoforged.fml.ModList;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Collections;
import java.util.List;

/**
 * Unlocks Clavis (lockpicking) containers and rolls their loot, purely
 * server-side, so an {@link com.sigmastrain.aiplayermod.brain.behavior.AreaLootBehavior}
 * can drain a sealed chest's spawnable items without a GUI or a lockpick item.
 *
 * <p>Reflection rather than a compile dependency, deliberately — the modpack is
 * frozen, and binding against Clavis + OctoLib would drag in jars we do not
 * control. The surface is small (three static methods, one static field, one
 * getter) so the failure mode is a logged no-op, not a mod that will not load.
 *
 * <p>What it calls, verified against clavis-1.21.1:
 * <pre>
 *   LockManager.isLocked(Level, Player, BlockPos) -> boolean
 *   LockManager.getLocksAt(ServerLevel, ServerPlayer, BlockPos) -> List&lt;Lock&gt;
 *   LootUtils.unlockWithQuality(ServerLevel, ServerPlayer, BlockPos, Lock, float)
 *   Clavis.CONFIG -> Config;  Config.getStartingQuality() -> float
 * </pre>
 * {@code unlockWithQuality} removes the lock, and when the block entity is a
 * {@code RandomizableContainerBlockEntity} holding a loot table it rolls that
 * table (the {@code quality} float drives the roll) and populates the container,
 * then {@code performOpen} marks the (Lootr) container opened. Items land in the
 * container — nothing is handed to a player — so the behavior drains the
 * container afterwards. Passing {@link #maxQuality()} (the config's starting
 * quality) is the highest roll a fresh player could ask for.
 */
public final class ClavisBridge {

    private ClavisBridge() {}

    private static final String CLAVIS_MOD_ID = "clavis";
    private static final String CLS_LOCK_MANAGER = "it.hurts.shatterbyte.clavis.common.LockManager";
    private static final String CLS_LOOT_UTILS = "it.hurts.shatterbyte.clavis.common.data.LootUtils";
    private static final String CLS_CLAVIS = "it.hurts.shatterbyte.clavis.common.Clavis";
    private static final String CLS_LOCK = "it.hurts.shatterbyte.clavis.common.data.Lock";
    private static final String CLS_CONFIG = "it.hurts.shatterbyte.clavis.common.config.Config";

    private static Boolean available;
    private static String initError;

    private static Method isLocked;
    private static Method getLocksAt;
    private static Method unlockWithQuality;
    private static Field configField;
    private static Method getStartingQuality;

    public static synchronized boolean isAvailable() {
        if (available != null) return available;
        if (!ModList.get().isLoaded(CLAVIS_MOD_ID)) {
            available = false;
            initError = "clavis is not loaded";
            return false;
        }
        try {
            Class<?> lockManager = Class.forName(CLS_LOCK_MANAGER);
            Class<?> lootUtils = Class.forName(CLS_LOOT_UTILS);
            Class<?> clavis = Class.forName(CLS_CLAVIS);
            Class<?> lock = Class.forName(CLS_LOCK);
            Class<?> config = Class.forName(CLS_CONFIG);

            isLocked = lockManager.getMethod("isLocked", Level.class, Player.class, BlockPos.class);
            getLocksAt = lockManager.getMethod("getLocksAt", ServerLevel.class, ServerPlayer.class, BlockPos.class);
            unlockWithQuality = lootUtils.getMethod("unlockWithQuality",
                    ServerLevel.class, ServerPlayer.class, BlockPos.class, lock, float.class);
            configField = clavis.getField("CONFIG");
            getStartingQuality = config.getMethod("getStartingQuality");

            available = true;
            AIPlayerMod.LOGGER.info("Clavis bridge active — bots can roll sealed-container loot");
        } catch (Throwable t) {
            available = false;
            initError = t.getClass().getSimpleName() + ": " + t.getMessage();
            AIPlayerMod.LOGGER.warn("Clavis present but its API did not match expectations ({}), "
                    + "area loot will skip locked containers", initError);
        }
        return available;
    }

    public static String unavailableReason() {
        isAvailable();
        return initError == null ? "unknown" : initError;
    }

    /** Whether Clavis has a lock sealing the container at {@code pos}. */
    public static boolean isLocked(Level level, Player player, BlockPos pos) {
        if (!isAvailable()) return false;
        try {
            return (boolean) isLocked.invoke(null, level, player, pos);
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("Clavis isLocked failed: {}", t.toString());
            return false;
        }
    }

    /** The locks sealing {@code pos}, as opaque handles for unlock. Empty when none. */
    public static List<Object> getLocksAt(ServerLevel level, ServerPlayer player, BlockPos pos) {
        if (!isAvailable()) return Collections.emptyList();
        try {
            Object raw = getLocksAt.invoke(null, level, player, pos);
            if (!(raw instanceof List<?> list)) return Collections.emptyList();
            List<Object> out = new java.util.ArrayList<>(list.size());
            out.addAll(list);
            return out;
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("Clavis getLocksAt failed: {}", t.toString());
            return Collections.emptyList();
        }
    }

    /** Roll one lock's loot into its container and mark it opened. */
    public static void unlockWithQuality(ServerLevel level, ServerPlayer player, BlockPos pos,
                                         Object lock, float quality) {
        if (!isAvailable() || lock == null) return;
        try {
            unlockWithQuality.invoke(null, level, player, pos, lock, quality);
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("Clavis unlockWithQuality failed: {}", t.toString());
        }
    }

    /** Highest starting quality the config offers — the best roll a fresh
     *  lockpicker could make, so a bot never under-rolls a locked chest. */
    public static float maxQuality() {
        if (!isAvailable()) return 1.0f;
        try {
            Object config = configField.get(null);
            if (config == null) return 1.0f;
            return (float) getStartingQuality.invoke(config);
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("Clavis maxQuality failed: {}", t.toString());
            return 1.0f;
        }
    }
}
