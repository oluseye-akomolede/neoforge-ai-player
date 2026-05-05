package com.sigmastrain.aiplayermod.compat.ae2;

import com.sigmastrain.aiplayermod.compat.ModCompat;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.level.ServerLevel;
import net.neoforged.neoforge.capabilities.Capabilities;
import net.neoforged.neoforge.items.IItemHandler;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public final class AE2Compat {
    private static final int DEFAULT_SEARCH_RADIUS = 16;

    private AE2Compat() {}

    public static boolean isAvailable() {
        return ModCompat.isAE2Loaded();
    }

    public static IItemHandler findNearestMEInterface(ServerLevel level, BlockPos origin, int radius) {
        if (!isAvailable()) return null;

        int r = radius > 0 ? radius : DEFAULT_SEARCH_RADIUS;
        List<InterfaceCandidate> found = new ArrayList<>();

        for (int x = -r; x <= r; x++) {
            for (int y = -r; y <= r; y++) {
                for (int z = -r; z <= r; z++) {
                    BlockPos pos = origin.offset(x, y, z);
                    IItemHandler handler = level.getCapability(Capabilities.ItemHandler.BLOCK, pos, Direction.UP);
                    if (handler != null && isMEInterface(level, pos)) {
                        double dist = origin.distSqr(pos);
                        found.add(new InterfaceCandidate(pos, handler, dist));
                    }
                }
            }
        }

        if (found.isEmpty()) return null;
        found.sort(Comparator.comparingDouble(InterfaceCandidate::distSqr));
        return found.getFirst().handler();
    }

    public static BlockPos findNearestMEInterfacePos(ServerLevel level, BlockPos origin, int radius) {
        if (!isAvailable()) return null;

        int r = radius > 0 ? radius : DEFAULT_SEARCH_RADIUS;
        BlockPos nearest = null;
        double nearestDist = Double.MAX_VALUE;

        for (int x = -r; x <= r; x++) {
            for (int y = -r; y <= r; y++) {
                for (int z = -r; z <= r; z++) {
                    BlockPos pos = origin.offset(x, y, z);
                    IItemHandler handler = level.getCapability(Capabilities.ItemHandler.BLOCK, pos, Direction.UP);
                    if (handler != null && isMEInterface(level, pos)) {
                        double dist = origin.distSqr(pos);
                        if (dist < nearestDist) {
                            nearestDist = dist;
                            nearest = pos;
                        }
                    }
                }
            }
        }

        return nearest;
    }

    private static boolean isMEInterface(ServerLevel level, BlockPos pos) {
        var blockState = level.getBlockState(pos);
        String blockName = blockState.getBlock().getDescriptionId();
        return blockName.contains("ae2") && blockName.contains("interface");
    }

    private record InterfaceCandidate(BlockPos pos, IItemHandler handler, double distSqr) {}
}
