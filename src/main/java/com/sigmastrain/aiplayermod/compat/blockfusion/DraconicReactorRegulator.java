package com.sigmastrain.aiplayermod.compat.blockfusion;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.brain.FusionControl;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.lang.reflect.Field;
import java.lang.reflect.Method;

/**
 * Regulates a Draconic Evolution reactor. It charges/activates the reactor, holds
 * the containment field ("shield") well above the danger line by driving the
 * field injection, and shuts down when temperature or shield leaves the safe
 * band. Production is the reactor's own {@code generationRate}, credited as FE.
 *
 * <p>Verified against DE 3.1.4: master BE {@code TileReactorCore} with public
 * {@code Managed*} fields ({@code get()}/{@code set(v)}): {@code reactorState}
 * (enum), {@code temperature} (+{@code MAX_TEMPERATURE}), {@code shieldCharge}/
 * {@code maxShieldCharge}, {@code saturation}/{@code maxSaturation},
 * {@code generationRate}, {@code fieldDrain}, {@code failSafeMode}; controls
 * {@code chargeReactor()/activateReactor()/shutdownReactor()/toggleFailSafe()}.
 */
public final class DraconicReactorRegulator implements Regulator {

    private static final double CONV_FE_PER_RF = 1.0;    // DE generationRate is already ~RF/t
    private static final double SAFE_TEMP = 0.90;        // fraction of MAX_TEMPERATURE
    private static final double MIN_SHIELD = 0.15;       // shield fraction that forces shutdown
    private static final double SHIELD_TARGET = 0.55;    // keep the field topped toward this

    private final Class<?> coreCls, reactorStateCls;
    private final Field fState, fTemp, fShield, fMaxShield, fSaturation, fMaxSaturation,
            fGenerationRate, fFieldDrain, fFieldInputRate, fFailSafe, fMaxTemp;
    private final Method mChargeReactor, mActivateReactor, mShutdownReactor, mCanActivate,
            mCanCharge, mIsStructureValid;
    private final Method mgGet, mgSet, mgGetD, mgSetD, mgGetL, mgSetL, mgGetE;

    public DraconicReactorRegulator() {
        if (!ModCompat.isDraconicLoaded()) throw new IllegalStateException("draconic absent");
        try {
            coreCls = Class.forName("com.brandon3055.draconicevolution.blocks.reactor.tileentity.TileReactorCore");
            reactorStateCls = Class.forName("com.brandon3055.draconicevolution.blocks.reactor.tileentity.TileReactorCore$ReactorState");
            fState = coreCls.getField("reactorState");
            fTemp = coreCls.getField("temperature");
            fMaxTemp = coreCls.getField("MAX_TEMPERATURE");
            fShield = coreCls.getField("shieldCharge");
            fMaxShield = coreCls.getField("maxShieldCharge");
            fSaturation = coreCls.getField("saturation");
            fMaxSaturation = coreCls.getField("maxSaturation");
            fGenerationRate = coreCls.getField("generationRate");
            fFieldDrain = coreCls.getField("fieldDrain");
            fFieldInputRate = coreCls.getField("fieldInputRate");
            fFailSafe = coreCls.getField("failSafeMode");
            mChargeReactor = coreCls.getMethod("chargeReactor");
            mActivateReactor = coreCls.getMethod("activateReactor");
            mShutdownReactor = coreCls.getMethod("shutdownReactor");
            mCanActivate = tryMethod(coreCls, "canActivate");
            mCanCharge = tryMethod(coreCls, "canCharge");
            mIsStructureValid = tryMethod(coreCls, "isStructureValid");
            Class<?> md = Class.forName("com.brandon3055.brandonscore.lib.datamanager.ManagedDouble");
            mgGetD = md.getMethod("get"); mgSetD = md.getMethod("set", double.class);
            Class<?> ml = Class.forName("com.brandon3055.brandonscore.lib.datamanager.ManagedLong");
            mgGetL = ml.getMethod("get"); mgSetL = ml.getMethod("set", long.class);
            Class<?> me = Class.forName("com.brandon3055.brandonscore.lib.datamanager.ManagedEnum");
            mgGetE = me.getMethod("get");
            Class<?> mi = Class.forName("com.brandon3055.brandonscore.lib.datamanager.ManagedInt");
            mgGet = mi.getMethod("get"); mgSet = mi.getMethod("set", int.class);
            AIPlayerMod.LOGGER.info("[BlockFusion] Draconic reactor regulator ready");
        } catch (Throwable t) {
            throw new IllegalStateException("draconic reactor API unresolved: " + t);
        }
    }

    private static Method tryMethod(Class<?> c, String n) {
        try { return c.getMethod(n); } catch (Throwable t) { return null; }
    }

    private double d(Field f, Object be) throws Exception { return ((Number) mgGetD.invoke(f.get(be))).doubleValue(); }
    private long l(Field f, Object be) throws Exception { return ((Number) mgGetL.invoke(f.get(be))).longValue(); }
    private int i(Field f, Object be) throws Exception { return ((Number) mgGet.invoke(f.get(be))).intValue(); }
    private String stateName(Object be) throws Exception {
        Object e = mgGetE.invoke(fState.get(be));
        return e == null ? "?" : e.toString();
    }

    @Override
    public boolean matches(BlockEntity be) {
        if (!coreCls.isInstance(be)) return false;
        try { return mIsStructureValid == null || (Boolean) mIsStructureValid.invoke(be); }
        catch (Throwable t) { return true; }
    }

    @Override
    public Snapshot read(BlockEntity be) {
        try {
            double temp = d(fTemp, be);
            double maxTemp = ((Number) fMaxTemp.get(be)).doubleValue();
            double shield = d(fShield, be);
            double maxShield = d(fMaxShield, be);
            double gen = d(fGenerationRate, be);
            String st = stateName(be);
            boolean running = "RUNNING".equalsIgnoreCase(st);
            double dmg = maxShield > 0 ? Math.max(0, 100.0 * (1.0 - shield / maxShield)) : 0;
            return new Snapshot(st, temp, maxTemp, shield, maxShield, dmg, gen, gen, running);
        } catch (Throwable t) {
            return new Snapshot("ERROR", 0, 1, 0, 1, 0, 0, 1, false);
        }
    }

    @Override
    public void regulate(BlockEntity be, FusionControl.Knobs knobs) {
        try {
            String st = stateName(be);
            double temp = d(fTemp, be);
            double maxTemp = ((Number) fMaxTemp.get(be)).doubleValue();
            double shield = d(fShield, be);
            double maxShield = d(fMaxShield, be);
            double shieldFrac = maxShield > 0 ? shield / maxShield : 1;

            // Bring it online if idle.
            if ("COLD".equalsIgnoreCase(st) || "INVALID".equalsIgnoreCase(st)) {
                if (mCanCharge == null || (Boolean) mCanCharge.invoke(be)) mChargeReactor.invoke(be);
                return;
            }
            if ("WARMING_UP".equalsIgnoreCase(st)) {
                if (shieldFrac >= SHIELD_TARGET && (mCanActivate == null || (Boolean) mCanActivate.invoke(be))) {
                    mActivateReactor.invoke(be);
                }
                return;
            }
            if (knobs.safeMode && "RUNNING".equalsIgnoreCase(st)) {
                if (shieldFrac <= MIN_SHIELD || temp >= maxTemp * SAFE_TEMP) { scram(be); return; }
            }
            // Hold the field: raise input rate when the shield is low, ease when high.
            double targetShield = Math.max(SHIELD_TARGET, 0.3 + 0.6 * Math.max(0, Math.min(1, knobs.targetRate)));
            double drain = i(fFieldDrain, be);
            double input = shieldFrac < targetShield
                    ? Math.max(drain, 1) * 1.5
                    : Math.max(drain, 1) * 1.05;
            mgSetD.invoke(fFieldInputRate.get(be), input);
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.debug("[BlockFusion] draconic regulate failed: {}", t.toString());
        }
    }

    @Override
    public void scram(BlockEntity be) {
        try {
            String st = stateName(be);
            if ("RUNNING".equalsIgnoreCase(st) || "WARMING_UP".equalsIgnoreCase(st)) mShutdownReactor.invoke(be);
        } catch (Throwable ignored) {
        }
    }

    @Override
    public long productionFe(BlockEntity be) {
        try {
            if (!"RUNNING".equalsIgnoreCase(stateName(be))) return 0;
            return (long) (d(fGenerationRate, be) * CONV_FE_PER_RF);
        } catch (Throwable t) {
            return 0;
        }
    }
}
