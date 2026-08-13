package com.sigmastrain.aiplayermod.brain.skill;

import com.sigmastrain.aiplayermod.brain.DirectiveType;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.Function;

/**
 * Static (registration-time) checks on a skill spec. A spec that fails any
 * check is rejected outright — an invalid skill must never reach the live
 * interpreter. Covers:
 *
 *   - every directive leaf names a real {@link DirectiveType} (and never
 *     {@code SKILL} — nesting goes through a skill-ref node, so the enum's
 *     one-active-directive invariant can't recurse into itself);
 *   - every condition uses a known predicate;
 *   - loops are bounded ({@code max_iterations > 0});
 *   - skill-refs name a registered skill and never the skill itself;
 *   - every {@code ${param}} reference is declared in {@code params}.
 */
public final class SkillValidator {

    private SkillValidator() {}

    public static List<String> validate(SkillSpec spec,
                                        Function<String, SkillSpec> registryLookup) {
        List<String> errors = new ArrayList<>();
        Set<String> referenced = new HashSet<>();
        walk(spec, spec.root, registryLookup, errors, referenced, 0);
        if (spec.verify != null) {
            if (!SkillCondition.KNOWN.contains(spec.verify.predicate)) {
                errors.add("skill '" + spec.id + "': verify uses unknown predicate '" + spec.verify.predicate + "'");
            }
            collectParams(spec.verify, referenced);
        }
        for (String p : referenced) {
            if (!spec.params.containsKey(p)) {
                errors.add("skill '" + spec.id + "': references undeclared param '${" + p + "}'");
            }
        }
        return errors;
    }

    private static void walk(SkillSpec spec, SkillNode node,
                             Function<String, SkillSpec> registryLookup,
                             List<String> errors, Set<String> referenced, int depth) {
        if (node == null || depth > 64) {
            if (depth > 64) errors.add("skill '" + spec.id + "': node tree too deep");
            return;
        }
        switch (node.type()) {
            case DIRECTIVE -> {
                DirectiveType dt = toType(node.kind());
                if (dt == null) {
                    errors.add("skill '" + spec.id + "': unknown directive kind '" + node.kind() + "'");
                } else if (dt == DirectiveType.SKILL) {
                    errors.add("skill '" + spec.id + "': a directive leaf must not be SKILL — use a skill-ref node");
                }
                collect(node.target(), referenced);
                collect(node.count(), referenced);
                collect(node.radius(), referenced);
                collect(node.x(), referenced);
                collect(node.y(), referenced);
                collect(node.z(), referenced);
                for (String v : node.extra().values()) collect(v, referenced);
            }
            case SEQUENCE, FALLBACK -> {
                for (SkillNode c : node.children()) walk(spec, c, registryLookup, errors, referenced, depth + 1);
            }
            case LOOP -> {
                if (node.maxIterations() <= 0) {
                    errors.add("skill '" + spec.id + "': loop has no positive max_iterations");
                }
                if (node.condition() != null) {
                    checkCondition(spec, node.condition(), referenced, errors);
                }
                walk(spec, node.body(), registryLookup, errors, referenced, depth + 1);
            }
            case IF -> {
                checkCondition(spec, node.condition(), referenced, errors);
                walk(spec, node.thenBranch(), registryLookup, errors, referenced, depth + 1);
                walk(spec, node.elseBranch(), registryLookup, errors, referenced, depth + 1);
            }
            case SKILL_REF -> {
                if (node.ref().equals(spec.id)) {
                    errors.add("skill '" + spec.id + "': self-reference via skill-ref");
                }
                if (registryLookup.apply(node.ref()) == null) {
                    errors.add("skill '" + spec.id + "': skill-ref to unregistered skill '" + node.ref() + "'");
                }
            }
        }
    }

    private static void checkCondition(SkillSpec spec, SkillCondition cond,
                                       Set<String> referenced, List<String> errors) {
        if (!SkillCondition.KNOWN.contains(cond.predicate)) {
            errors.add("skill '" + spec.id + "': unknown predicate '" + cond.predicate + "'");
        }
        collectParams(cond, referenced);
    }

    private static void collectParams(SkillCondition cond, Set<String> referenced) {
        for (var e : cond.args.entrySet()) {
            if (e.getValue().isJsonPrimitive()) {
                collect(e.getValue().getAsString(), referenced);
            }
        }
    }

    private static DirectiveType toType(String kind) {
        if (kind == null) return null;
        try {
            return DirectiveType.valueOf(kind);
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    private static void collect(String template, Set<String> referenced) {
        if (template == null || template.indexOf("${") < 0) return;
        int i = 0;
        while ((i = template.indexOf("${", i)) >= 0) {
            int close = template.indexOf('}', i + 2);
            if (close < 0) break;
            referenced.add(template.substring(i + 2, close));
            i = close + 1;
        }
    }
}
