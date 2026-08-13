package com.sigmastrain.aiplayermod.brain.skill;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The ever-expanding skill library (Decision 5 of the v10 design). Seeded with
 * five curated skills at server start; runtime self-expansion (Phase 2) adds
 * validated specs through the same {@link #register} path. Reads happen on the
 * server thread; the map is concurrent so catalog HTTP reads never block the
 * tick loop.
 */
public final class SkillRegistry {

    private static final Logger LOGGER = LoggerFactory.getLogger("aiplayermod.skill");

    private static final Map<String, SkillSpec> SKILLS = new ConcurrentHashMap<>();

    private SkillRegistry() {}

    /** Register a spec after static validation. Returns null on success, or the
     *  joined validation errors. Never silently accepts an invalid skill. */
    public static String register(String id, SkillSpec spec) {
        List<String> errors = SkillValidator.validate(spec, SkillRegistry::get);
        if (!errors.isEmpty()) {
            return "skill '" + id + "' rejected: " + String.join("; ", errors);
        }
        SkillSpec previous = SKILLS.put(spec.id, spec);
        LOGGER.info("[skill] registered {}", spec.id);
        if (previous != null) {
            LOGGER.info("[skill] replaced existing {}", spec.id);
        }
        return null;
    }

    public static SkillSpec get(String id) {
        return id == null ? null : SKILLS.get(id);
    }

    public static boolean has(String id) {
        return SKILLS.containsKey(id);
    }

    public static int size() {
        return SKILLS.size();
    }

    public static List<Map<String, Object>> catalog() {
        List<Map<String, Object>> out = new ArrayList<>();
        SKILLS.values().stream()
                .sorted(Comparator.comparing(s -> s.id))
                .forEach(s -> out.add(s.toCatalogEntry()));
        return out;
    }

    /** Five curated seed skills. Each is a bounded sequence over real directive
     *  kinds so the whole set is headless-testable in the aiplayermod world. */
    public static void initSeeds() {
        int before = SKILLS.size();
        seed("mine_and_smelt", "Mine N ore blocks, then smelt them into ingots.",
                """
                { "type": "sequence", "children": [
                    { "type": "directive", "kind": "MINE", "target": "${target}", "count": "${count}" },
                    { "type": "directive", "kind": "SMELT", "target": "${target}", "count": "${count}" }
                ] }
                """,
                "target:item_id", "count:int");

        seed("goto_and_scan", "Teleport to a location, then wide-search for a target.",
                """
                { "type": "sequence", "children": [
                    { "type": "directive", "kind": "TELEPORT", "x": "${x}", "y": "${y}", "z": "${z}" },
                    { "type": "directive", "kind": "WIDE_SEARCH", "target": "${target}" }
                ] }
                """,
                "x:int", "y:int", "z:int", "target:block_or_entity");

        seed("search_and_loot", "Search containers for an item, then store everything.",
                """
                { "type": "sequence", "children": [
                    { "type": "directive", "kind": "CONTAINER_SEARCH", "target": "${item}", "count": "${count}" },
                    { "type": "directive", "kind": "STORE_ALL" }
                ] }
                """,
                "item:item_id", "count:int");

        seed("harvest_and_store", "Farm N crops, then store the yield.",
                """
                { "type": "sequence", "children": [
                    { "type": "directive", "kind": "FARM", "target": "${crop}", "count": "${count}" },
                    { "type": "directive", "kind": "STORE_ALL" }
                ] }
                """,
                "crop:item_id", "count:int");

        seed("resupply_network", "Conjure a material and send it to a player.",
                """
                { "type": "sequence", "children": [
                    { "type": "directive", "kind": "CHANNEL", "target": "${item}", "count": "${count}" },
                    { "type": "directive", "kind": "SEND_ITEM", "target": "${to}", "extra": { "item": "${item}", "count": "${count}" } }
                ] }
                """,
                "item:item_id", "count:int", "to:player");

        LOGGER.info("[skill] seeded {} skills", SKILLS.size() - before);
    }

    private static void seed(String id, String description, String nodesJson, String... params) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"id\":\"").append(id).append("\",")
          .append("\"description\":\"").append(description).append("\",")
          .append("\"params\":{");
        for (int i = 0; i < params.length; i++) {
            String[] kv = params[i].split(":", 2);
            if (i > 0) sb.append(",");
            sb.append("\"").append(kv[0]).append("\":\"").append(kv[1]).append("\"");
        }
        sb.append("},\"nodes\":").append(nodesJson).append("}");
        String err = register(id, SkillSpec.parse(sb.toString()));
        if (err != null) {
            LOGGER.error("[skill] seed failed: {}", err);
        }
    }
}
