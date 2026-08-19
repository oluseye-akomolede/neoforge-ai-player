package com.sigmastrain.aiplayermod.compat.blockfusion;

import com.sigmastrain.aiplayermod.brain.FusionControl;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * A reactor "brain" a fused bot runs each tick. Implementations reflect one
 * mod's reactor multiblock (Mekanism fission, Draconic reactor, …) and expose a
 * uniform surface so {@code ManageFusionBehavior} can keep any reactor safe and
 * hive can credit FE from its production — without either knowing the mod.
 */
public interface Regulator {

    /** Does this regulator handle the block entity at a fused pos? */
    boolean matches(BlockEntity be);

    /** Read the reactor's live state for display/regulation. */
    Snapshot read(BlockEntity be);

    /** Drive the reactor toward the knobs' target while keeping it in a safe band. */
    void regulate(BlockEntity be, FusionControl.Knobs knobs);

    /** Emergency stop. */
    void scram(BlockEntity be);

    /**
     * Instantaneous production, in FE/tick equivalent, that fusion should credit
     * to the reservoir (before the reactor buff multiplier). 0 if idle.
     */
    long productionFe(BlockEntity be);

    /** Uniform reactor readout for the overlay + API. */
    record Snapshot(String state, double temperature, double maxTemperature,
                    double shield, double maxShield, double damagePercent,
                    double rate, double maxRate, boolean running) {
        public Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("state", state);
            m.put("temperature", temperature);
            m.put("max_temperature", maxTemperature);
            m.put("shield", shield);
            m.put("max_shield", maxShield);
            m.put("damage_percent", damagePercent);
            m.put("rate", rate);
            m.put("max_rate", maxRate);
            m.put("running", running);
            return m;
        }
    }
}
