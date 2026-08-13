package com.sigmastrain.aiplayermod.bot;

import net.minecraft.world.Container;
import net.minecraft.world.item.ItemStack;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Extension seam: other mods bolt extra equipment slots onto a bot's
 * equipment window. Hive uses this for officer HARDPOINTS — shoulder
 * mounts that are neither armor nor hand slots, but must still be
 * swappable in-game like any other gear.
 *
 * <p>Providers hand back a {@link Container} so vanilla slot mechanics
 * (click, drag, shift-click) work unchanged; the provider is responsible
 * for persisting whatever the player puts there.
 */
public final class AuxSlots {

    private AuxSlots() {}

    public interface Provider {
        /** @return null when this bot has no aux slots from this provider. */
        Container containerFor(String botName);

        /** Labels, one per slot — drawn under the slot in the panel. */
        List<String> labels(String botName);

        /** @return false to refuse a stack in that slot. */
        default boolean accepts(String botName, int index, ItemStack stack) {
            return true;
        }
    }

    private static final List<Provider> PROVIDERS = new ArrayList<>();

    public static synchronized void register(Provider p) {
        PROVIDERS.add(p);
    }

    public static synchronized List<Provider> providers() {
        return Collections.unmodifiableList(new ArrayList<>(PROVIDERS));
    }

    /** The first provider that claims this bot, or null. */
    public static Provider providerFor(String botName) {
        for (Provider p : providers()) {
            if (p.containerFor(botName) != null) return p;
        }
        return null;
    }
}
