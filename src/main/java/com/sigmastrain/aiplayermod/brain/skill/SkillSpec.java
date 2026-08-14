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
 *   "verify": { "predicate": "inventory.has", "item": "${target}", "count": "${count}" },
 *   "produces": "minecraft:iron_ingot"
 * }
 * }</pre>
 *
 * {@code params} is schema documentation only (all values arrive as strings in
 * the SKILL directive's extra map); {@code verify} is the optional post-run
 * predicate that turns an otherwise-successful completion into a FAILED result
 * when the world state doesn't back it up. {@code produces} is an optional
 * override for the skill's terminal held item — absent by default, in which
 * case {@link SkillOutputResolver} infers it from the node tree.
 */
public final class SkillSpec {

    public final String id;
    public final String description;
    public final Map<String, String> params;
    public final SkillNode root;
    public final SkillCondition verify;
    public final String produces;

    private SkillSpec(String id, String description, Map<String, String> params,
                      SkillNode root, SkillCondition verify, String produces) {
        this.id = id;
        this.description = description;
        this.params = params;
        this.root = root;
        this.verify = verify;
        this.produces = produces;
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
        String produces = (o.has("produces") && !o.get("produces").isJsonNull())
                ? o.get("produces").getAsString()
                : null;
        return new SkillSpec(id, desc, params, root, verify, produces);
    }

    public Map<String, Object> toCatalogEntry() {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("id", id);
        entry.put("description", description);
        entry.put("params", params);
        entry.put("verify", verify != null ? verify.predicate : null);
        entry.put("produces", produces);
        return entry;
    }

    /** A copy of this spec under a different id — used by runtime
     *  self-expansion, which registers under a generated key so an
     *  L3-proposed spec can never clobber a curated seed. */
    public SkillSpec withId(String newId) {
        return new SkillSpec(newId, description, params, root, verify, produces);
    }
}
