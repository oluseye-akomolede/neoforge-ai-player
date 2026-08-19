package com.sigmastrain.aiplayermod.compat.blockfusion;

import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.util.ArrayList;
import java.util.List;

/** Which {@link Regulator} (if any) manages a block. Extend by registering more. */
public final class RegulatorRegistry {

    private RegulatorRegistry() {}

    private static volatile boolean inited;
    private static final List<Regulator> REGULATORS = new ArrayList<>();

    public static synchronized void register(Regulator r) {
        REGULATORS.add(r);
    }

    private static synchronized void init() {
        if (inited) return;
        inited = true;
        // Ship two; the seam is open for Powah/Extreme/Oritech/MI/fusion reactors.
        try { REGULATORS.add(new MekanismFissionRegulator()); } catch (Throwable ignored) {}
        try { REGULATORS.add(new DraconicReactorRegulator()); } catch (Throwable ignored) {}
    }

    /** The regulator for the block at pos, or null if it isn't a managed reactor. */
    public static Regulator regulatorFor(ServerLevel level, BlockPos pos) {
        init();
        BlockEntity be = level.getBlockEntity(pos);
        if (be == null) return null;
        for (Regulator r : REGULATORS) {
            try {
                if (r.matches(be)) return r;
            } catch (Throwable ignored) {
            }
        }
        return null;
    }
}
