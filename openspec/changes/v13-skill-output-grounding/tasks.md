# v13 tasks — Skill output grounding

Mod + agent; no l2-mcp or L3 prompt change.

- [ ] **`produces` field** — `SkillSpec.java`: parse `produces` (nullable
      string), store on the spec, expose in `toCatalogEntry`, thread through
      `withId`.
- [ ] **Expose smelt/drop accessors** — `SmeltBehavior.resolveOutput(String)`
      public static; `MineBehavior.resolveDropItem` → `public static String
      resolveDrop(String)` with the two call sites (lines 83, 275) updated.
- [ ] **`SkillOutputResolver`** — new class walking the node tree with
      held-item threading; `resolve(skillId, params) → String|null`.
- [ ] **`/skills/resolve` endpoint** — `HttpApiServer` context + handler
      (`skill` query param + extra params; returns `{skill, output,
      resolved_by}`; 404 on unknown skill, 400 on missing `skill`).
- [ ] **`api.skill_output(skill_id, **params)`** — agent-side GET helper.
- [ ] **`_ground_skill_criteria`** — `plan_orchestrator.py`; hook after
      `_derive_build_criteria` in `_step`; `_is_real_item` registry-lookup
      guard (fail-open).
- [ ] **Proof — headless** — `gradle compileJava` (COMPILE_OK); `python3 -m
      py_compile api.py plan_orchestrator.py criteria_eval.py` (PY_COMPILE_OK);
      a resolver unit check: `mine_and_smelt` with `target=iron_ore` →
      `minecraft:iron_ingot`; `goto_and_scan` → null; `resupply_network` → null.
- [ ] **Deploy + retest** — mod jar → MinIO `minecraft-mods/test/lightweight/`;
      agent image → Harbor `aiplayermod/agent:latest`; restart the test agent;
      rerun `l3_emits_skill` (expect: criteria loop grounds
      `iron_ore_blocks` → `iron_ingot`, no `Unknown item ID` CHANNEL).
