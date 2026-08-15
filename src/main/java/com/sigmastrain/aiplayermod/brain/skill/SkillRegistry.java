package com.sigmastrain.aiplayermod.brain.skill;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonParser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The ever-expanding skill library (Decision 5 of the v10 design). Seeded with
 * five curated skills at server start; runtime self-expansion (Phase 2) adds
 * validated specs through the same {@link #register} path, capped at
 * {@link #MAX_SKILLS} with least-recently-used eviction (curated seeds are
 * never evicted).
 *
 * A synchronized {@link LinkedHashMap} in access-order backs true LRU and lets
 * every method stay a single atomic operation. The map is tiny (≤64 entries)
 * and read only at directive-start / catalog time, never per-tick, so the
 * class-level monitor is never contended.
 */
public final class SkillRegistry {

    private static final Logger LOGGER = LoggerFactory.getLogger("aiplayermod.skill");

    /** Cap for runtime self-expansion; seeds (5) always fit, so eviction only
     *  ever recycles previously self-expanded skills. */
    private static final int MAX_SKILLS = 64;

    private static final Map<String, SkillSpec> SKILLS =
            new LinkedHashMap<>(MAX_SKILLS, 0.75f, /* accessOrder */ true);

    /** Curated ids registered by {@link #initSeeds}; exempt from LRU eviction. */
    private static final Set<String> SEEDS = new LinkedHashSet<>();

    /** On-disk file for authored (non-seed) skills, under the world save dir.
     *  Null until {@link #initPersistence} wires it at server start. */
    private static Path savePath = null;

    /** True while {@link #load()} is re-registering persisted skills, so the
     *  write-through save in {@link #register} doesn't rewrite the file mid-load. */
    private static boolean loading = false;

    private SkillRegistry() {}

    /** Register a spec after static validation. Stores under {@code id} (which
     *  may differ from {@code spec.id} for generated self-expansion keys).
     *  Returns null on success, or the joined validation errors. Never silently
     *  accepts an invalid skill. */
    public static synchronized String register(String id, SkillSpec spec) {
        List<String> errors = SkillValidator.validate(spec, SkillRegistry::get);
        if (!errors.isEmpty()) {
            return "skill '" + id + "' rejected: " + String.join("; ", errors);
        }
        evictIfNeeded(id);
        SkillSpec stored = id.equals(spec.id) ? spec : spec.withId(id);
        SkillSpec previous = SKILLS.put(id, stored);
        LOGGER.info("[skill] registered {}", id);
        if (previous != null) {
            LOGGER.info("[skill] replaced existing {}", id);
        }
        // Write-through so a crash between registers and shutdown can't lose a
        // freshly authored skill. No-op until a save path is configured.
        if (!loading) {
            save();
        }
        return null;
    }

    /** Register a curated cross-mod skill as a seed — exempt from LRU eviction
     *  and, crucially, from on-disk persistence. The latter is what lets a
     *  dependent mod (hive-mod) contribute an always-present skill through the
     *  same seam as the built-in seeds: {@link #load()} skips seed ids, so a
     *  stale copy that an earlier run persisted under {@link #register} can
     *  never clobber the fresh registration at boot. Returns null on success,
     *  or the joined validation errors. */
    public static synchronized String registerSeed(String id, SkillSpec spec) {
        SEEDS.add(id); // curated — exempt from LRU eviction and persistence
        String err = register(id, spec);
        if (err != null) {
            SEEDS.remove(id); // don't leave a half-registered seed behind
        }
        return err;
    }

    /** Drop the least-recently-used non-seed entry to stay under {@link #MAX_SKILLS}. */
    private static void evictIfNeeded(String incomingId) {
        if (SKILLS.containsKey(incomingId) || SKILLS.size() < MAX_SKILLS) {
            return;
        }
        String victim = null;
        for (String key : SKILLS.keySet()) {           // access-order: eldest first
            if (!SEEDS.contains(key)) { victim = key; break; }
        }
        if (victim == null) victim = SKILLS.keySet().iterator().next();
        LOGGER.info("[skill] evicting LRU {} (cap {})", victim, MAX_SKILLS);
        SKILLS.remove(victim);
    }

    public static synchronized SkillSpec get(String id) {
        return id == null ? null : SKILLS.get(id);
    }

    public static synchronized boolean has(String id) {
        return SKILLS.containsKey(id);
    }

    public static synchronized int size() {
        return SKILLS.size();
    }

    public static synchronized List<Map<String, Object>> catalog() {
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
                    { "type": "directive", "kind": "WIDE_SEARCH", "target": "${target}", "extra": { "bot_index": "${bot_index}", "bot_count": "${bot_count}" } }
                ] }
                """,
                "x:int", "y:int", "z:int", "target:block_or_entity", "bot_index:int", "bot_count:int");

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
        SEEDS.add(id); // curated — exempt from LRU eviction
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

    // ── persistence ─────────────────────────────────────────────────────────

    /** Wire on-disk persistence to the world-save directory and load any
     *  previously authored skills. MUST run after {@link #initSeeds()} so the
     *  seeds are registered first (persisted skills may reference them via a
     *  skill-ref node, and a stale file must never clobber a curated seed). */
    public static synchronized void initPersistence(Path path) {
        savePath = path;
        load();
    }

    /** Load authored skills from disk, re-validating each through the same
     *  {@link #register} path (a corrupt or hand-edited file can never poison
     *  the registry). Seeds are skipped — they're already registered. */
    public static synchronized void load() {
        if (savePath == null || !Files.exists(savePath)) {
            return;
        }
        try {
            JsonElement root = JsonParser.parseString(Files.readString(savePath));
            if (!root.isJsonArray()) {
                LOGGER.warn("[skill] persistence file is not a JSON array; ignoring");
                return;
            }
            loading = true;
            int loaded = 0;
            for (JsonElement el : root.getAsJsonArray()) {
                if (!el.isJsonObject()) continue;
                try {
                    SkillSpec spec = SkillSpec.parse(el.getAsJsonObject());
                    if (SEEDS.contains(spec.id)) continue;
                    String err = register(spec.id, spec);
                    if (err == null) {
                        loaded++;
                    } else {
                        LOGGER.warn("[skill] load rejected '{}': {}", spec.id, err);
                    }
                } catch (Exception e) {
                    LOGGER.warn("[skill] load skipped an entry: {}", e.getMessage());
                }
            }
            LOGGER.info("[skill] loaded {} authored skill(s)", loaded);
        } catch (Exception e) {
            LOGGER.warn("[skill] load failed", e);
        } finally {
            loading = false;
        }
    }

    /** Write authored (non-seed) skills to disk. No-op until a save path is
     *  configured. Best-effort: a failed write must never break the bot. */
    public static synchronized void save() {
        if (savePath == null) return;
        JsonArray arr = new JsonArray();
        for (Map.Entry<String, SkillSpec> e : SKILLS.entrySet()) {
            if (SEEDS.contains(e.getKey())) continue;
            arr.add(e.getValue().toJson());
        }
        try {
            Path parent = savePath.getParent();
            if (parent != null) Files.createDirectories(parent);
            Files.writeString(savePath, arr.toString());
        } catch (Exception e) {
            LOGGER.warn("[skill] save failed", e);
        }
    }
}
