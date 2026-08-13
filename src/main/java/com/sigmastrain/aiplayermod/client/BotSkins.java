package com.sigmastrain.aiplayermod.client;

import com.sigmastrain.aiplayermod.client.overlay.OverlayClientState;
import net.minecraft.resources.ResourceLocation;

import java.util.Map;

/**
 * Fleet identity, visually (design ruling): the five originals wear black
 * bodies with a solid signature-colored head; drones are black with pure
 * white heads — the swarm reads as the swarm at a glance. Future golems
 * follow the same language on golem bodies (near-black, white heads).
 *
 * <p>Husks are untouched: a husk carries the PLAYER's own profile, whose
 * name is never in the fleet snapshot.
 */
public final class BotSkins {

    private BotSkins() {}

    private static final Map<String, ResourceLocation> ORIGINALS = Map.of(
            "Axiom", tex("bot_axiom"),
            "Forge", tex("bot_forge"),
            "Mystic", tex("bot_mystic"),
            "Scout", tex("bot_scout"),
            "Tiller", tex("bot_tiller"));

    private static final ResourceLocation DRONE = tex("drone");

    private static ResourceLocation tex(String name) {
        return ResourceLocation.fromNamespaceAndPath("aiplayermod",
                "textures/entity/" + name + ".png");
    }

    /** @return the custom skin for this profile name, or null for real players. */
    public static ResourceLocation forName(String name) {
        ResourceLocation original = ORIGINALS.get(name);
        if (original != null) return original;
        // Every other fleet member (drones now, golem escorts later)
        // wears swarm colors. Snapshot membership is the bot test.
        for (var e : OverlayClientState.snapshot().bots()) {
            if (e.name().equals(name)) return DRONE;
        }
        return name.startsWith("Drone") ? DRONE : null;
    }
}
