package com.sigmastrain.aiplayermod.brain.skill;

import com.sigmastrain.aiplayermod.brain.behavior.MineBehavior;
import com.sigmastrain.aiplayermod.brain.behavior.SmeltBehavior;

import java.util.Map;
import java.util.Objects;

/**
 * Deterministic skill-output resolution — the runtime half of criteria
 * grounding. Walks a skill's node tree threading the item the bot ends up
 * *holding* after a full run, so the agent can rewrite a hallucinated
 * completion criterion ("inventory has 8 iron_ore_blocks") to the skill's real
 * output ("minecraft:iron_ingot").
 *
 * <p>Item-transformation semantics live mod-side — {@code MineBehavior}'s drop
 * table and {@code SmeltBehavior}'s SMELTING_RECIPES — and this resolver only
 * composes them, it never re-encodes. An optional {@code produces} override on
 * the spec short-circuits the walk for skills whose output isn't inferable
 * from the tree.
 *
 * <p>Returns {@code null} when the output cannot be determined (non-material
 * skills like goto_and_scan, or unknown inputs) — callers treat null as "no
 * grounding".
 */
public final class SkillOutputResolver {

    private SkillOutputResolver() {}

    public static String resolve(String skillId, Map<String, String> params) {
        SkillSpec spec = SkillRegistry.get(skillId);
        if (spec == null) {
            return null;
        }
        if (spec.produces != null) {
            return substitute(spec.produces, params);
        }
        return resolveNode(spec.root, params, null);
    }

    /** Thread a "held item" through the node. Returns the terminal held item,
     *  or null when a node leaves it undeterminable. */
    private static String resolveNode(SkillNode node, Map<String, String> params, String held) {
        if (node == null) return held;
        return switch (node.type()) {
            case DIRECTIVE -> applyDirective(node, params, held);
            case SEQUENCE -> {
                String cur = held;
                for (SkillNode child : node.children()) {
                    cur = resolveNode(child, params, cur);
                }
                yield cur;
            }
            case LOOP -> resolveNode(node.body(), params, held);   // one iteration = the output
            case SKILL_REF -> resolve(node.ref(), params);        // nested skill's output (params shared)
            case FALLBACK -> agreeOrNull(node.children(), params, held);
            case IF -> {
                String then = resolveNode(node.thenBranch(), params, held);
                String els = resolveNode(node.elseBranch(), params, held);
                // elseBranch may be absent (no-op -> held) — treat null branch as held.
                String elsResolved = node.elseBranch() == null ? held : els;
                yield Objects.equals(then, elsResolved) ? then : null;
            }
        };
    }

    /** Conservative for branching: only confident when every branch agrees. */
    private static String agreeOrNull(Iterable<SkillNode> branches, Map<String, String> params, String held) {
        String result = null;
        boolean first = true;
        for (SkillNode child : branches) {
            String r = resolveNode(child, params, held);
            if (first) { result = r; first = false; }
            else if (!Objects.equals(result, r)) { return null; }
        }
        return result;
    }

    private static String applyDirective(SkillNode node, Map<String, String> params, String held) {
        String kind = node.kind() == null ? "" : node.kind().toUpperCase();
        String target = substitute(node.target(), params);
        return switch (kind) {
            case "MINE" -> MineBehavior.resolveDrop(target);          // ore -> raw drop
            case "SMELT" -> {
                // Smelt consumes the held raw, not the ore target.
                String input = held != null ? held : target;
                yield SmeltBehavior.resolveOutput(input);
            }
            case "CHANNEL" -> {
                // A channeled GUN lands as the gun MOD's item (TaCZ: every gun is
                // tacz:modern_kinetic_gun with the model in components), not as an
                // item named after the gun id. Grounding criteria on "tacz:p90"
                // produced an unsatisfiable "holdings 0/1" loop that re-channeled
                // the gun every retry. Resolve to the item that actually appears.
                var g = com.sigmastrain.aiplayermod.compat.guns.GunConjure.resolve(target);
                if (g != null) {
                    yield g.kind() == com.sigmastrain.aiplayermod.compat.guns.GunConjure.Kind.TACZ
                            ? "tacz:modern_kinetic_gun" : g.idString();
                }
                yield target;
            }
            case "FARM", "CONTAINER_SEARCH", "WITHDRAW",
                 "CONTAINER_WITHDRAW", "CONTAINER_EXTRACT" -> target; // acquire/put target in hand
            case "SEND_ITEM" -> null;                                 // item leaves the bot
            default -> held;                                          // TELEPORT / STORE_ALL / WIDE_SEARCH / ...
        };
    }

    /** Resolve {@code ${param}} templates (mirrors SkillBehavior's leaf
     *  resolution, scoped to the SKILL directive's extra map). */
    private static String substitute(String template, Map<String, String> params) {
        if (template == null) return null;
        String out = template;
        for (Map.Entry<String, String> e : params.entrySet()) {
            out = out.replace("${" + e.getKey() + "}", e.getValue() == null ? "" : e.getValue());
        }
        return out;
    }
}
