package com.sigmastrain.aiplayermod.brain.skill;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * One node of a skill's control-flow tree. Parsed from declarative JSON
 * (Decision 1 of the v10 design). Types:
 *
 * <pre>{@code
 *   { "type": "sequence",  "children": [ ... ] }                 // all in order
 *   { "type": "fallback",  "children": [ ... ] }                 // first that succeeds
 *   { "type": "loop",      "body": { ... }, "max_iterations": N, "while": {condition} }
 *   { "type": "if",        "condition": { ... }, "then": { ... }, "else": { ... } }
 *   { "type": "skill",     "ref": "mine_and_smelt" }             // nested skill
 *   { "type": "directive", "kind": "MINE", "target": "${target}", "count": "${count}", ... }
 * }</pre>
 *
 * There is deliberately no single-bot parallel node: a bot has one active
 * directive and one inventory, so intra-skill parallelism can only corrupt
 * state. Sequence/loop/if/fallback/skill-ref are the complete vocabulary.
 *
 * Directive-leaf numeric fields accept a literal number or a {@code "${param}"}
 * string resolved at execution time. {@link SkillBehavior} is the only caller
 * that resolves those templates.
 */
public final class SkillNode {

    public enum Type { SEQUENCE, LOOP, IF, FALLBACK, SKILL_REF, DIRECTIVE }

    private final Type type;
    // composite
    private final List<SkillNode> children;   // sequence / fallback
    private final SkillNode body;             // loop
    private final SkillNode thenBranch;       // if
    private final SkillNode elseBranch;       // if (nullable)
    private final SkillCondition condition;   // if / loop "while" (nullable)
    private final int maxIterations;          // loop
    private final String ref;                 // skill-ref
    // directive leaf (templates, resolved at runtime)
    private final String kind;
    private final String target;
    private final String count;
    private final String radius;
    private final String x, y, z;
    private final boolean hasLocation;
    private final Map<String, String> extra;

    private SkillNode(Type type, List<SkillNode> children, SkillNode body, SkillNode thenBranch,
                      SkillNode elseBranch, SkillCondition condition, int maxIterations, String ref,
                      String kind, String target, String count, String radius,
                      String x, String y, String z, boolean hasLocation, Map<String, String> extra) {
        this.type = type;
        this.children = children;
        this.body = body;
        this.thenBranch = thenBranch;
        this.elseBranch = elseBranch;
        this.condition = condition;
        this.maxIterations = maxIterations;
        this.ref = ref;
        this.kind = kind;
        this.target = target;
        this.count = count;
        this.radius = radius;
        this.x = x;
        this.y = y;
        this.z = z;
        this.hasLocation = hasLocation;
        this.extra = extra;
    }

    public static SkillNode parse(JsonElement el, String path) {
        if (el == null || !el.isJsonObject()) {
            throw new IllegalArgumentException(path + ": node must be a JSON object");
        }
        JsonObject o = el.getAsJsonObject();
        String typeStr = o.has("type") ? o.get("type").getAsString() : "";
        Type type = switch (typeStr) {
            case "sequence" -> Type.SEQUENCE;
            case "fallback" -> Type.FALLBACK;
            case "loop" -> Type.LOOP;
            case "if" -> Type.IF;
            case "skill", "skill_ref", "ref" -> Type.SKILL_REF;
            case "directive", "action" -> Type.DIRECTIVE;
            default -> throw new IllegalArgumentException(path + ": unknown node type '" + typeStr + "'");
        };

        switch (type) {
            case SEQUENCE, FALLBACK -> {
                JsonArray kids = requireArray(o, "children", path);
                if (kids.isEmpty()) {
                    throw new IllegalArgumentException(path + ": " + typeStr + " needs at least one child");
                }
                List<SkillNode> parsed = new ArrayList<>();
                for (int i = 0; i < kids.size(); i++) {
                    parsed.add(parse(kids.get(i), path + ".children[" + i + "]"));
                }
                return new SkillNode(type, parsed, null, null, null, null, 0, null,
                        null, null, null, null, null, null, null, false, null);
            }
            case LOOP -> {
                if (!o.has("body")) {
                    throw new IllegalArgumentException(path + ": loop needs a 'body'");
                }
                int max = o.has("max_iterations") ? o.get("max_iterations").getAsInt() : 0;
                if (max <= 0) {
                    throw new IllegalArgumentException(path + ": loop needs max_iterations > 0");
                }
                SkillCondition whileCond = o.has("while")
                        ? SkillCondition.parse(o.getAsJsonObject("while"), path + ".while")
                        : null;
                SkillNode b = parse(o.get("body"), path + ".body");
                return new SkillNode(Type.LOOP, null, b, null, null, whileCond, max, null,
                        null, null, null, null, null, null, null, false, null);
            }
            case IF -> {
                if (!o.has("condition") || !o.has("then")) {
                    throw new IllegalArgumentException(path + ": if needs 'condition' and 'then'");
                }
                SkillCondition cond = SkillCondition.parse(o.getAsJsonObject("condition"), path + ".condition");
                SkillNode thenN = parse(o.get("then"), path + ".then");
                SkillNode elseN = o.has("else") ? parse(o.get("else"), path + ".else") : null;
                return new SkillNode(Type.IF, null, null, thenN, elseN, cond, 0, null,
                        null, null, null, null, null, null, null, false, null);
            }
            case SKILL_REF -> {
                if (!o.has("ref") && !o.has("skill")) {
                    throw new IllegalArgumentException(path + ": skill-ref needs 'ref'");
                }
                String ref = o.has("ref") ? o.get("ref").getAsString() : o.get("skill").getAsString();
                if (ref == null || ref.isBlank()) {
                    throw new IllegalArgumentException(path + ": skill-ref name is blank");
                }
                return new SkillNode(Type.SKILL_REF, null, null, null, null, null, 0, ref,
                        null, null, null, null, null, null, null, false, null);
            }
            case DIRECTIVE -> {
                if (!o.has("kind")) {
                    throw new IllegalArgumentException(path + ": directive needs 'kind'");
                }
                String kind = o.get("kind").getAsString();
                String target = str(o, "target");
                String count = str(o, "count");
                String radius = str(o, "radius");
                String x = str(o, "x");
                String y = str(o, "y");
                String z = str(o, "z");
                boolean hasLoc = o.has("x") && o.has("y") && o.has("z");
                Map<String, String> extra = new LinkedHashMap<>();
                if (o.has("extra") && o.get("extra").isJsonObject()) {
                    for (var e : o.getAsJsonObject("extra").entrySet()) {
                        extra.put(e.getKey(), e.getValue().getAsString());
                    }
                }
                return new SkillNode(Type.DIRECTIVE, null, null, null, null, null, 0, null,
                        kind, target, count, radius, x, y, z, hasLoc, extra);
            }
        }
        throw new IllegalArgumentException(path + ": unhandled node type " + type);
    }

    private static JsonArray requireArray(JsonObject o, String key, String path) {
        if (!o.has(key) || !o.get(key).isJsonArray()) {
            throw new IllegalArgumentException(path + ": missing '" + key + "' array");
        }
        return o.getAsJsonArray(key);
    }

    private static String str(JsonObject o, String key) {
        JsonElement e = o.get(key);
        if (e == null || e.isJsonNull()) return null;
        return e.isJsonPrimitive() ? e.getAsString() : e.toString();
    }

    // ── accessors ──────────────────────────────────────────────────────────

    public Type type() { return type; }
    public List<SkillNode> children() { return children == null ? Collections.emptyList() : children; }
    public SkillNode body() { return body; }
    public SkillNode thenBranch() { return thenBranch; }
    public SkillNode elseBranch() { return elseBranch; }
    public SkillCondition condition() { return condition; }
    public int maxIterations() { return maxIterations; }
    public String ref() { return ref; }
    public String kind() { return kind; }
    public String target() { return target; }
    public String count() { return count; }
    public String radius() { return radius; }
    public String x() { return x; }
    public String y() { return y; }
    public String z() { return z; }
    public boolean hasLocation() { return hasLocation; }
    public Map<String, String> extra() { return extra == null ? Collections.emptyMap() : extra; }
}
