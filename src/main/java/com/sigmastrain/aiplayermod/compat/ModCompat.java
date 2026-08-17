package com.sigmastrain.aiplayermod.compat;

import net.neoforged.fml.ModList;

public final class ModCompat {
    private static Boolean ae2Loaded;
    private static Boolean betterCombatLoaded;
    private static Boolean taczLoaded;
    private static Boolean superbWarfareLoaded;

    private ModCompat() {}

    public static boolean isAE2Loaded() {
        if (ae2Loaded == null) {
            ae2Loaded = ModList.get().isLoaded("ae2");
        }
        return ae2Loaded;
    }

    public static boolean isBetterCombatLoaded() {
        if (betterCombatLoaded == null) {
            betterCombatLoaded = ModList.get().isLoaded("bettercombat");
        }
        return betterCombatLoaded;
    }

    public static boolean isTaczLoaded() {
        if (taczLoaded == null) {
            taczLoaded = ModList.get().isLoaded("tacz");
        }
        return taczLoaded;
    }

    public static boolean isSuperbWarfareLoaded() {
        if (superbWarfareLoaded == null) {
            superbWarfareLoaded = ModList.get().isLoaded("superbwarfare");
        }
        return superbWarfareLoaded;
    }
}
