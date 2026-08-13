package com.sigmastrain.aiplayermod.client.overlay;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Registry of {@link OverlayTab}s mounted by other mods (client-side). */
public final class OverlayExtensions {

    private OverlayExtensions() {}

    private static final List<OverlayTab> TABS = new ArrayList<>();

    public static synchronized void register(OverlayTab tab) {
        TABS.add(tab);
    }

    public static synchronized List<OverlayTab> tabs() {
        return Collections.unmodifiableList(new ArrayList<>(TABS));
    }
}
