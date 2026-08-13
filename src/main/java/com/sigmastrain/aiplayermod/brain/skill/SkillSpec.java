package com.sigmastrain.aiplayermod.brain.skill;

import com.google.gson.JsonObject;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * A parsed skill spec — the declarative unit of the L1 skill layer.
 *
 * <pre>{@code
 * {
 *   "id": "mine_and_smelt",
 *   "description": "Mine N ore, then smelt it.",
 *   "params": { "target": "item_id", "count": "int" },
 *   "nodes": { "type": "sequence", "children": [ ... ] },
 *   "verify": { "predicate": "inventory.has", "item": "${target}", "count": "${count}" }
 * }
 * }</pre>
 *
 * {@code params} is schema documentation only (all values arrive as strings in
 * the SKILL directive's extra map); {@code verify} is the optional post-run
 * predicate that turns an otherwise-successful completion into a FAILED result
 * when the world state doesn't back it up.
 */
public final class SkillSpec {

    public final String id;
    public final String description;
    public final Map<String, String> params;
    public final SkillNode root;
    public final SkillCondition verify;

    private SkillSpec(String id, String description, Map<String, String> params,
                      SkillNode root, SkillCondition verify) {
        this.id = id;
        this.description = description;
        this.params = params;
        this.root = root;
        this.verify = verify;
    }

    public static SkillSpec parse(String json) {
        return parse(com.google.gson.JsonParser.parseString(json).getAsJsonObject());
    }

    public static SkillSpec parse(JsonObject o) {
        if (!o.has("id")) throw new IllegalArgumentException("skill spec missing 'id'");
        String id = o.get("id").getAsString();
        String desc = o.has("description") ? o.get("description").getAsString() : "";
        Map<String, String> params = new LinkedHashMap<>();
        if (o.has("params") && o.get("params").isJsonObject()) {
            for (var e : o.getAsJsonObject("params").entrySet()) {
                params.put(e.getKey(), e.getValue().getAsString());
            }
        }
        if (!o.has("nodes")) throw new IllegalArgumentException("skill '" + id + "' missing 'nodes'");
        SkillNode root = SkillNode.parse(o.get("nodes"), "skill '" + id + "'.nodes");
        SkillCondition verify = o.has("verify")
                ? SkillCondition.parse(o.getAsJsonObject("verify"), "skill '" + id + "'.verify")
                : null;
        return new SkillSpec(id, desc, params, root, verify);
    }

    public Map<String, Object> toCatalogEntry() {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("id", id);
        entry.put("description", description);
        entry.put("params", params);
        entry.put("verify", verify != null ? verify.predicate : null);
        return entry;
    }
}
