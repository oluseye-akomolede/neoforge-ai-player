package com.sigmastrain.aiplayermod.brain.skill;

import java.util.Map;

/**
 * `${param}` substitution for skill leaf directives and conditions.
 * Params arrive at runtime via the SKILL directive's {@code extra} map
 * (e.g. {@code target=minecraft:iron_ore, count=16}); a leaf template
 * references them by name. Unbound references are left in place so a
 * typo is visible in the failure reason rather than silently dropped.
 */
public final class SkillParams {

    private SkillParams() {}

    public static String substitute(String template, Map<String, String> params) {
        if (template == null || template.isEmpty() || template.indexOf("${") < 0) {
            return template;
        }
        StringBuilder out = new StringBuilder(template.length());
        int i = 0;
        while (i < template.length()) {
            int open = template.indexOf("${", i);
            if (open < 0) {
                out.append(template, i, template.length());
                break;
            }
            out.append(template, i, open);
            int close = template.indexOf('}', open + 2);
            if (close < 0) {
                out.append(template, open, template.length());
                break;
            }
            String name = template.substring(open + 2, close);
            String value = params.get(name);
            out.append(value != null ? value : template.substring(open, close + 1));
            i = close + 1;
        }
        return out.toString();
    }
}
