package com.sigmastrain.aiplayermod.compat.blockfusion;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Reflection bridge to a Hostile Neural Networks <b>Simulation Chamber</b>
 * ({@code SimChamberTileEntity}). A fused bot turns the chamber into an
 * autonomous mob-loot farm: hive powers it and clears its output (and, on a
 * knob, materializes blank prediction matrices) while this reads its live state
 * and sets its mode.
 *
 * <p>The chamber's energy is a standard {@code IEnergyStorage} and its item
 * ports are standard {@code IItemHandler}s, so power and item movement go
 * through {@link BlockFusionCompat}'s generic capability paths — this class only
 * reflects the bits with no capability: the current model, tier/accuracy,
 * runtime, failure state, and the INFERENCE/TRAINING mode.
 *
 * <p>Verified against HNN 6.5.1 ({@code dev.shadowsoffire.hostilenetworks}):
 * {@code SimChamberTileEntity.getEnergyStored()/getEnergy()/getRuntime()/
 * getFailState()/getSimMode()/setSimMode()/didPredictionSucceed()}, field
 * {@code currentModel} ({@code DataModelInstance}); {@code DataModelInstance
 * .getModel()/getTier()/getAccuracy()/isValid()}; {@code DataModel.name()/
 * simCost()}; {@code ModelTier.name()/accuracy()}; {@code SimMode} values
 * {@code INFERENCE}/{@code TRAINING}.
 */
public final class SimChamberCompat {

    private SimChamberCompat() {}

    private static volatile boolean tried;
    private static boolean ok;

    private static Class<?> simTile, simModeCls;
    private static Method mGetEnergyStored, mGetEnergy, mGetRuntime, mGetFailState,
            mGetSimMode, mSetSimMode, mDidPredict, mCanStart;
    private static Field fCurrentModel;
    private static Method mGetModel, mGetTier, mGetAccuracy, mIsValid, mName, mSimCost, mTierName;
    private static Object simModeInference, simModeTraining;

    private static synchronized void resolve() {
        if (tried) return;
        tried = true;
        if (!ModCompat.isHnnLoaded()) return;
        try {
            simTile = Class.forName("dev.shadowsoffire.hostilenetworks.tile.SimChamberTileEntity");
            mGetEnergyStored = simTile.getMethod("getEnergyStored");
            mGetEnergy = simTile.getMethod("getEnergy");
            mGetRuntime = simTile.getMethod("getRuntime");
            mGetFailState = simTile.getMethod("getFailState");
            mGetSimMode = simTile.getMethod("getSimMode");
            mDidPredict = tryMethod(simTile, "didPredictionSucceed");
            mCanStart = tryMethod(simTile, "canStartSimulation");
            fCurrentModel = simTile.getDeclaredField("currentModel");
            fCurrentModel.setAccessible(true);

            simModeCls = Class.forName("dev.shadowsoffire.hostilenetworks.tile.SimChamberTileEntity$SimMode");
            mSetSimMode = simTile.getMethod("setSimMode", simModeCls);
            for (Object c : simModeCls.getEnumConstants()) {
                String n = ((Enum<?>) c).name();
                if (n.equals("INFERENCE")) simModeInference = c;
                else if (n.equals("TRAINING")) simModeTraining = c;
            }

            Class<?> instCls = Class.forName("dev.shadowsoffire.hostilenetworks.data.DataModelInstance");
            mGetModel = instCls.getMethod("getModel");
            mGetTier = instCls.getMethod("getTier");
            mGetAccuracy = instCls.getMethod("getAccuracy");
            mIsValid = instCls.getMethod("isValid");
            Class<?> modelCls = Class.forName("dev.shadowsoffire.hostilenetworks.data.DataModel");
            mName = modelCls.getMethod("name");
            mSimCost = modelCls.getMethod("simCost");
            Class<?> tierCls = Class.forName("dev.shadowsoffire.hostilenetworks.data.ModelTier");
            mTierName = tierCls.getMethod("name");

            ok = true;
            AIPlayerMod.LOGGER.info("[BlockFusion] HNN simulation-chamber bridge resolved");
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.debug("[BlockFusion] HNN sim-chamber unresolved: {}", t.toString());
        }
    }

    private static Method tryMethod(Class<?> c, String n) {
        try { return c.getMethod(n); } catch (Throwable t) { return null; }
    }

    public static boolean isAvailable() {
        resolve();
        return ok;
    }

    /** Is the block at pos a HNN simulation chamber? */
    public static boolean isSimChamber(ServerLevel level, BlockPos pos) {
        resolve();
        if (!ok) return false;
        BlockEntity be = level.getBlockEntity(pos);
        return be != null && simTile.isInstance(be);
    }

    private static Object tile(ServerLevel level, BlockPos pos) {
        BlockEntity be = level.getBlockEntity(pos);
        return be != null && simTile.isInstance(be) ? be : null;
    }

    /** Set the chamber's mode from a knob string ("inference"/"training"). */
    public static void setMode(ServerLevel level, BlockPos pos, String mode) {
        Object be = tile(level, pos);
        if (be == null || mSetSimMode == null) return;
        Object target = "training".equalsIgnoreCase(mode) ? simModeTraining : simModeInference;
        if (target == null) return;
        try { mSetSimMode.invoke(be, target); } catch (Throwable ignored) {}
    }

    /** The chamber's current failure/idle reason ("NONE","ENERGY","INPUT","OUTPUT","MODEL",…) or "". */
    public static String failState(ServerLevel level, BlockPos pos) {
        Object be = tile(level, pos);
        if (be == null) return "";
        try {
            Object f = mGetFailState.invoke(be);
            return f == null ? "" : ((Enum<?>) f).name();
        } catch (Throwable t) { return ""; }
    }

    /** True when the chamber is idle for lack of a blank prediction matrix. */
    public static boolean needsMatrix(ServerLevel level, BlockPos pos) {
        return "INPUT".equals(failState(level, pos));
    }

    /** Max FE the chamber's buffer can still take (for hive to top up). */
    public static long powerDeficit(ServerLevel level, BlockPos pos) {
        Object be = tile(level, pos);
        if (be == null) return 0;
        try {
            Object es = mGetEnergy.invoke(be);
            int max = (int) es.getClass().getMethod("getMaxEnergyStored").invoke(es);
            int cur = (int) es.getClass().getMethod("getEnergyStored").invoke(es);
            return Math.max(0, (long) max - cur);
        } catch (Throwable t) { return 0; }
    }

    /** Live readout for the fusion status/overlay. Never throws. */
    public static Map<String, Object> read(ServerLevel level, BlockPos pos) {
        Map<String, Object> m = new LinkedHashMap<>();
        Object be = tile(level, pos);
        if (be == null) return m;
        try {
            m.put("energy", ((Number) mGetEnergyStored.invoke(be)).intValue());
            Object es = mGetEnergy.invoke(be);
            m.put("max_energy", (int) es.getClass().getMethod("getMaxEnergyStored").invoke(es));
            m.put("runtime", ((Number) mGetRuntime.invoke(be)).intValue());
            Object fail = mGetFailState.invoke(be);
            m.put("fail_state", fail == null ? "" : ((Enum<?>) fail).name());
            Object sm = mGetSimMode.invoke(be);
            m.put("sim_mode", sm == null ? "" : ((Enum<?>) sm).name());
            if (mDidPredict != null) m.put("last_prediction", mDidPredict.invoke(be));

            Object inst = fCurrentModel.get(be);
            if (inst != null && (mIsValid == null || (Boolean) mIsValid.invoke(inst))) {
                Object model = mGetModel.invoke(inst);
                if (model != null) {
                    m.put("model", ((net.minecraft.network.chat.Component) mName.invoke(model)).getString());
                    m.put("sim_cost", ((Number) mSimCost.invoke(model)).intValue());
                }
                Object tier = mGetTier.invoke(inst);
                if (tier != null) m.put("tier", (String) mTierName.invoke(tier));
                m.put("accuracy", ((Number) mGetAccuracy.invoke(inst)).floatValue());
            } else {
                m.put("model", "");
            }
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.debug("[BlockFusion] sim read failed: {}", t.toString());
        }
        return m;
    }
}
