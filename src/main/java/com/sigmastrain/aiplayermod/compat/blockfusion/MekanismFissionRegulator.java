package com.sigmastrain.aiplayermod.compat.blockfusion;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.brain.FusionControl;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.lang.reflect.Field;
import java.lang.reflect.Method;

/**
 * Regulates a Mekanism fission reactor. The bot holds the reactor at the knobs'
 * target burn rate (as a fraction of max) and, in safe mode, backs the rate off
 * and finally deactivates before temperature or damage reaches the danger band.
 * A fission reactor produces heated coolant, not FE, so its "production" is its
 * boil rate — hive credits FE proportional to that.
 *
 * <p>Verified against MekanismGenerators 10.7:
 * {@code IMultiblock.getMultiblock()} → {@code FissionReactorMultiblockData}
 * with public {@code heatCapacitor.getTemperature()}, {@code getDamagePercent()},
 * {@code getCoolantFilledPercentage()}, {@code getMaxBurnRate()},
 * {@code setRateLimit(double)}, {@code setActive(boolean)}, {@code isActive()},
 * {@code lastBoilRate}, {@code MAX_DAMAGE_TEMPERATURE}.
 */
public final class MekanismFissionRegulator implements Regulator {

    private static final double CONV_FE_PER_MB = 20.0;   // boil rate (mB/t) → FE/t before buff
    private static final double SAFE_TEMP_FRAC = 0.85;   // back off above this fraction of danger temp
    private static final double SAFE_DAMAGE = 60.0;      // % damage that forces a scram
    private static final double MIN_COOLANT = 0.15;      // coolant fill below which we throttle hard

    private final Class<?> imultiblock;
    private final Class<?> dataCls;
    private final Method getMultiblock, getTemp, getDamagePercent, getCoolantFill, getMaxBurnRate,
            setRateLimit, setActive, isActive, isFormed;
    private final Field heatCapacitorF, lastBoilRateF, maxDamageTempF;
    private final Method heatGetTemperature;

    public MekanismFissionRegulator() {
        if (!ModCompat.isMekanismLoaded()) throw new IllegalStateException("mekanism absent");
        try {
            imultiblock = Class.forName("mekanism.common.lib.multiblock.IMultiblock");
            getMultiblock = imultiblock.getMethod("getMultiblock");
            dataCls = Class.forName("mekanism.generators.common.content.fission.FissionReactorMultiblockData");
            heatCapacitorF = dataCls.getField("heatCapacitor");
            lastBoilRateF = dataCls.getField("lastBoilRate");
            maxDamageTempF = dataCls.getField("MAX_DAMAGE_TEMPERATURE");
            getDamagePercent = dataCls.getMethod("getDamagePercent");
            getCoolantFill = dataCls.getMethod("getCoolantFilledPercentage");
            getMaxBurnRate = dataCls.getMethod("getMaxBurnRate");
            setRateLimit = dataCls.getMethod("setRateLimit", double.class);
            setActive = dataCls.getMethod("setActive", boolean.class);
            isActive = dataCls.getMethod("isActive");
            Class<?> multiblockData = Class.forName("mekanism.common.lib.multiblock.MultiblockData");
            isFormed = multiblockData.getMethod("isFormed");
            heatGetTemperature = Class.forName("mekanism.api.heat.IHeatCapacitor").getMethod("getTemperature");
            getTemp = heatGetTemperature;
            AIPlayerMod.LOGGER.info("[BlockFusion] Mekanism fission regulator ready");
        } catch (Throwable t) {
            throw new IllegalStateException("mekanism fission API unresolved: " + t);
        }
    }

    private Object data(BlockEntity be) {
        if (!imultiblock.isInstance(be)) return null;
        try {
            Object d = getMultiblock.invoke(be);
            if (d == null || !dataCls.isInstance(d)) return null;
            if (!(Boolean) isFormed.invoke(d)) return null;
            return d;
        } catch (Throwable t) {
            return null;
        }
    }

    @Override
    public boolean matches(BlockEntity be) {
        String n = be.getClass().getName();
        return n.startsWith("mekanism.generators.common.tile.fission.") && data(be) != null;
    }

    private double temperature(Object data) throws Exception {
        Object heat = heatCapacitorF.get(data);
        return ((Number) heatGetTemperature.invoke(heat)).doubleValue();
    }

    @Override
    public Snapshot read(BlockEntity be) {
        Object data = data(be);
        if (data == null) return new Snapshot("UNFORMED", 0, 1, 0, 0, 0, 0, 1, false);
        try {
            double temp = temperature(data);
            double maxTemp = ((Number) maxDamageTempF.get(data)).doubleValue();
            double dmg = ((Number) getDamagePercent.invoke(data)).doubleValue();
            double maxBurn = ((Number) getMaxBurnRate.invoke(data)).doubleValue();
            boolean active = (Boolean) isActive.invoke(data);
            double boil = ((Number) lastBoilRateF.get(data)).doubleValue();
            return new Snapshot(active ? "RUNNING" : "IDLE", temp, maxTemp, 0, 0, dmg,
                    boil, maxBurn, active);
        } catch (Throwable t) {
            return new Snapshot("ERROR", 0, 1, 0, 0, 0, 0, 1, false);
        }
    }

    @Override
    public void regulate(BlockEntity be, FusionControl.Knobs knobs) {
        Object data = data(be);
        if (data == null) return;
        try {
            double maxBurn = ((Number) getMaxBurnRate.invoke(data)).doubleValue();
            double target = Math.max(0, Math.min(1, knobs.targetRate)) * maxBurn;

            if (knobs.safeMode) {
                double dmg = ((Number) getDamagePercent.invoke(data)).doubleValue();
                double temp = temperature(data);
                double maxTemp = ((Number) maxDamageTempF.get(data)).doubleValue();
                double coolant = ((Number) getCoolantFill.invoke(data)).doubleValue();
                if (dmg >= SAFE_DAMAGE) { scram(be); return; }
                if (temp >= maxTemp * SAFE_TEMP_FRAC) target = Math.min(target, maxBurn * 0.25);
                if (coolant < MIN_COOLANT) target = Math.min(target, maxBurn * 0.1);
            }
            setRateLimit.invoke(data, target);
            boolean active = (Boolean) isActive.invoke(data);
            if (!active && target > 0) setActive.invoke(data, true);
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.debug("[BlockFusion] fission regulate failed: {}", t.toString());
        }
    }

    @Override
    public void scram(BlockEntity be) {
        Object data = data(be);
        if (data == null) return;
        try {
            setRateLimit.invoke(data, 0.0);
            setActive.invoke(data, false);
        } catch (Throwable ignored) {
        }
    }

    @Override
    public long productionFe(BlockEntity be) {
        Object data = data(be);
        if (data == null) return 0;
        try {
            if (!(Boolean) isActive.invoke(data)) return 0;
            double boil = ((Number) lastBoilRateF.get(data)).doubleValue();
            return (long) (boil * CONV_FE_PER_MB);
        } catch (Throwable t) {
            return 0;
        }
    }
}
