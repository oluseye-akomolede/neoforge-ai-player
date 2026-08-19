package com.sigmastrain.aiplayermod.compat.blockfusion;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.lang.reflect.Field;
import java.lang.reflect.Method;

/**
 * Native {@code long} energy accessors for storages whose FE capability caps out
 * at {@code Integer.MAX_VALUE} (Mekanism Induction Matrix, Draconic Energy Core,
 * Powah high-tier cells, Flux storage, …). Reflection-only, resolved lazily per
 * mod; anything unresolved just falls back to the int capability upstream.
 */
final class NativeEnergy {

    private NativeEnergy() {}

    private static volatile boolean resolved;
    // Mekanism
    private static Method mekGetMultiblock, mekMatrixEnergy, mekMatrixCap;
    private static Class<?> mekMultiblockIface, mekMatrixData;
    // Draconic
    private static Class<?> deEnergyCore;
    private static Field deEnergyField;
    private static Method deOpStored, deOpMax;
    // Powah
    private static Class<?> powahStorage;
    private static Field powahEnergyField;
    private static Method powahEnergyStored, powahEnergyCap;

    static synchronized void resolve() {
        if (resolved) return;
        try {
            if (ModCompat.isMekanismLoaded()) {
                try {
                    mekMultiblockIface = Class.forName("mekanism.common.lib.multiblock.IMultiblock");
                    mekGetMultiblock = mekMultiblockIface.getMethod("getMultiblock");
                    mekMatrixData = Class.forName("mekanism.common.content.matrix.MatrixMultiblockData");
                    mekMatrixEnergy = mekMatrixData.getMethod("getEnergy");
                    mekMatrixCap = mekMatrixData.getMethod("getStorageCap");
                    BlockFusionCompat.logResolve("Mekanism", true);
                } catch (Throwable t) {
                    BlockFusionCompat.logResolve("Mekanism", false);
                }
            }
            if (ModCompat.isDraconicLoaded()) {
                try {
                    deEnergyCore = Class.forName("com.brandon3055.draconicevolution.blocks.tileentity.TileEnergyCore");
                    deEnergyField = deEnergyCore.getField("energy");
                    Class<?> opStorage = Class.forName("com.brandon3055.brandonscore.api.power.IOPStorage");
                    deOpStored = opStorage.getMethod("getOPStored");
                    deOpMax = opStorage.getMethod("getMaxOPStored");
                    BlockFusionCompat.logResolve("Draconic Evolution", true);
                } catch (Throwable t) {
                    BlockFusionCompat.logResolve("Draconic Evolution", false);
                }
            }
            if (ModCompat.isPowahLoaded()) {
                try {
                    powahStorage = Class.forName("owmii.powah.lib.block.AbstractEnergyStorage");
                    powahEnergyField = powahStorage.getDeclaredField("energy");
                    powahEnergyField.setAccessible(true);
                    Class<?> energy = Class.forName("owmii.powah.lib.logistics.energy.Energy");
                    powahEnergyStored = energy.getMethod("getStored");
                    powahEnergyCap = energy.getMethod("getCapacity");
                    BlockFusionCompat.logResolve("Powah", true);
                } catch (Throwable t) {
                    BlockFusionCompat.logResolve("Powah", false);
                }
            }
        } finally {
            resolved = true;
        }
    }

    static boolean hasNative(ServerLevel level, BlockPos pos) {
        resolve();
        BlockEntity be = level.getBlockEntity(pos);
        return be != null && (isMekMultiblock(be) || (deEnergyCore != null && deEnergyCore.isInstance(be))
                || (powahStorage != null && powahStorage.isInstance(be)));
    }

    /** True for the pack's known >int energy STORAGE blocks (so role detection picks STORAGE). */
    static boolean isKnownStorage(ServerLevel level, BlockPos pos) {
        resolve();
        BlockEntity be = level.getBlockEntity(pos);
        if (be == null) return false;
        String n = be.getClass().getName();
        return n.contains("InductionCasing") || n.contains("InductionPort") || n.contains("InductionCell")
                || n.contains("TileEnergyCore") || n.contains("EnergyCellTile")
                || n.contains("TileFluxStorage") || n.contains("ModularAccumulator")
                || n.contains("EnergizerController") || n.contains("EnergizerPowerPort")
                || n.contains("CapacitorBank");
    }

    /**
     * A block that PRODUCES energy (a generator), distinguished from a battery by
     * its block-entity class name. Both a generator and a battery can extract, so
     * capability flags alone can't tell them apart; this recognises the common
     * generator families so {@code roleOf} classifies them as GENERATOR (divert +
     * amplify their output) instead of STORAGE (add their buffer to the FE cap).
     * Names are matched case-insensitively as substrings of the BE class.
     */
    static boolean isKnownGenerator(ServerLevel level, BlockPos pos) {
        BlockEntity be = level.getBlockEntity(pos);
        if (be == null) return false;
        String n = be.getClass().getName().toLowerCase();
        // A battery/cell is never a generator, even if a token below matches.
        if (n.contains("energycell") || n.contains("capacitor") || n.contains("accumulator")
                || n.contains("energycube") || n.contains("fluxstorage")) return false;
        return n.contains("furnator") || n.contains("magmator") || n.contains("reactor")
                || n.contains("thermo") || n.contains("solar") || n.contains("dynamo")
                || n.contains("generator") || n.contains("turbine") || n.contains("combustion")
                || n.contains("reformer") || n.contains("windmill") || n.contains("waterwheel")
                || n.contains("bioreactor") || n.contains("alternator") || n.contains("energizing")
                || n.contains("photovoltaic");
    }

    static long maxEnergy(ServerLevel level, BlockPos pos) {
        resolve();
        BlockEntity be = level.getBlockEntity(pos);
        if (be == null) return -1;
        try {
            if (isMekMultiblock(be)) {
                Object data = mekGetMultiblock.invoke(be);
                if (mekMatrixData.isInstance(data)) return ((Number) mekMatrixCap.invoke(data)).longValue();
            }
            if (deEnergyCore != null && deEnergyCore.isInstance(be)) {
                Object op = deEnergyField.get(be);
                if (op != null) return ((Number) deOpMax.invoke(op)).longValue();
            }
            if (powahStorage != null && powahStorage.isInstance(be)) {
                Object en = powahEnergyField.get(be);
                if (en != null) return ((Number) powahEnergyCap.invoke(en)).longValue();
            }
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.debug("[BlockFusion] native maxEnergy failed: {}", t.toString());
        }
        return -1;
    }

    static long stored(ServerLevel level, BlockPos pos) {
        resolve();
        BlockEntity be = level.getBlockEntity(pos);
        if (be == null) return -1;
        try {
            if (isMekMultiblock(be)) {
                Object data = mekGetMultiblock.invoke(be);
                if (mekMatrixData.isInstance(data)) return ((Number) mekMatrixEnergy.invoke(data)).longValue();
            }
            if (deEnergyCore != null && deEnergyCore.isInstance(be)) {
                Object op = deEnergyField.get(be);
                if (op != null) return ((Number) deOpStored.invoke(op)).longValue();
            }
            if (powahStorage != null && powahStorage.isInstance(be)) {
                Object en = powahEnergyField.get(be);
                if (en != null) return ((Number) powahEnergyStored.invoke(en)).longValue();
            }
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.debug("[BlockFusion] native stored failed: {}", t.toString());
        }
        return -1;
    }

    private static boolean isMekMultiblock(BlockEntity be) {
        return mekMultiblockIface != null && mekMultiblockIface.isInstance(be);
    }
}
