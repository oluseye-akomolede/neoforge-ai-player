package com.sigmastrain.aiplayermod.compat.blockfusion;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.neoforged.neoforge.capabilities.Capabilities;
import net.neoforged.neoforge.energy.IEnergyStorage;

import java.util.ArrayList;
import java.util.List;

/**
 * Reads and writes the energy of any block a bot fuses with. NeoForge's
 * {@code Capabilities.EnergyStorage.BLOCK} exposes an {@link IEnergyStorage} on
 * almost every energy block in this pack (Powah, Mekanism, Draconic, Extreme
 * Reactors, EnderIO, Oritech, createaddition, Flux Networks, Industrial
 * Foregoing, MI, Integrated Dynamics…), so generation and storage fusion work
 * generically with zero per-mod code.
 *
 * <p>Two things the plain capability can't do, handled by reflection:
 * <ul>
 *   <li>the cap is an {@code int}, so storages above ~2.1 B FE saturate — for
 *   those, {@link #longMaxEnergy}/{@link #longStored} read the mod-native
 *   {@code long} accessor;</li>
 *   <li>reactors that don't self-store FE (Mekanism fission, Draconic reactor)
 *   need internal-state regulation — {@link RegulatorRegistry} plugs those in.</li>
 * </ul>
 *
 * <p>This class is economy-agnostic: it moves FE in and out of the world block;
 * hive decides what that means for the cultivation reservoir.
 */
public final class BlockFusionCompat {

    private BlockFusionCompat() {}

    /** What kind of energy block this is (drives the fusion economy). */
    public enum Role { GENERATOR, STORAGE, REACTOR, NONE }

    /** Any energy mod present makes fusion available (capability is universal). */
    public static boolean isAvailable() {
        // The capability itself is always there under NeoForge; there's nothing to resolve.
        return true;
    }

    private static final Direction[] SIDES;
    static {
        List<Direction> s = new ArrayList<>();
        s.add(null);                       // side-agnostic first
        for (Direction d : Direction.values()) s.add(d);
        SIDES = s.toArray(new Direction[0]);
    }

    /** The IEnergyStorage exposed by the block, trying null side then every face, or null. */
    public static IEnergyStorage energy(ServerLevel level, BlockPos pos) {
        for (Direction d : SIDES) {
            IEnergyStorage e = level.getCapability(Capabilities.EnergyStorage.BLOCK, pos, d);
            if (e != null) return e;
        }
        return null;
    }

    public static boolean isEnergyBlock(ServerLevel level, BlockPos pos) {
        return energy(level, pos) != null || RegulatorRegistry.regulatorFor(level, pos) != null;
    }

    // ── generic energy (int) ──────────────────────────────────────────────

    public static int stored(ServerLevel level, BlockPos pos) {
        IEnergyStorage e = energy(level, pos);
        return e == null ? 0 : e.getEnergyStored();
    }

    public static int maxEnergy(ServerLevel level, BlockPos pos) {
        IEnergyStorage e = energy(level, pos);
        return e == null ? 0 : e.getMaxEnergyStored();
    }

    public static boolean canExtract(ServerLevel level, BlockPos pos) {
        IEnergyStorage e = energy(level, pos);
        return e != null && e.canExtract();
    }

    public static boolean canReceive(ServerLevel level, BlockPos pos) {
        IEnergyStorage e = energy(level, pos);
        return e != null && e.canReceive();
    }

    /** Pull up to {@code amount} FE out of the block; returns the amount removed. */
    public static int extract(ServerLevel level, BlockPos pos, int amount) {
        IEnergyStorage e = energy(level, pos);
        if (e == null || amount <= 0 || !e.canExtract()) return 0;
        return e.extractEnergy(amount, false);
    }

    /** Push up to {@code amount} FE into the block; returns the amount accepted. */
    public static int receive(ServerLevel level, BlockPos pos, int amount) {
        IEnergyStorage e = energy(level, pos);
        if (e == null || amount <= 0 || !e.canReceive()) return 0;
        return e.receiveEnergy(amount, false);
    }

    // ── native long capacity (for >int storages) ──────────────────────────

    /** Max energy as a long — reflects the mod-native accessor when the int cap saturates. */
    public static long longMaxEnergy(ServerLevel level, BlockPos pos) {
        long l = NativeEnergy.maxEnergy(level, pos);
        if (l > 0) return l;
        int cap = maxEnergy(level, pos);
        return cap == Integer.MAX_VALUE ? Integer.MAX_VALUE : cap;
    }

    public static long longStored(ServerLevel level, BlockPos pos) {
        long l = NativeEnergy.stored(level, pos);
        if (l >= 0 && (l > 0 || NativeEnergy.hasNative(level, pos))) return l;
        return stored(level, pos);
    }

    // ── role + identity ───────────────────────────────────────────────────

    public static Role roleOf(ServerLevel level, BlockPos pos) {
        if (RegulatorRegistry.regulatorFor(level, pos) != null) return Role.REACTOR;
        IEnergyStorage e = energy(level, pos);
        if (e == null) return Role.NONE;
        // Storage: can receive and holds a lot; generator: extract-oriented.
        boolean recv = e.canReceive();
        boolean ext = e.canExtract();
        long max = longMaxEnergy(level, pos);
        if (recv && (max >= 5_000_000L || NativeEnergy.isKnownStorage(level, pos))) return Role.STORAGE;
        if (ext) return Role.GENERATOR;
        if (recv) return Role.STORAGE;
        return Role.NONE;
    }

    public static String blockName(ServerLevel level, BlockPos pos) {
        BlockEntity be = level.getBlockEntity(pos);
        if (be != null) {
            try { return Component.translatable(be.getBlockState().getBlock().getDescriptionId()).getString(); }
            catch (Exception ignored) {}
        }
        return level.getBlockState(pos).getBlock().getName().getString();
    }

    static void logResolve(String what, boolean ok) {
        if (ok) AIPlayerMod.LOGGER.info("[BlockFusion] {} energy bridge resolved", what);
        else AIPlayerMod.LOGGER.debug("[BlockFusion] {} not present", what);
    }
}
