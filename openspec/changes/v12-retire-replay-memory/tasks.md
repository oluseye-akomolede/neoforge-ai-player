# v12 tasks — Retire the behavioral replay memory

Agent-side only; no mod change.

- [x] **Delete the behavioral write** — remove `_store_plan_outcome`
      (`agent.py:1236`) and its 7 call sites (424, 477, 606, 827, 2458, 2528,
      2563). Keep `_store_success_memory`, `_learn_from_error`,
      `_inject_knowledge`, `_set_work_area`, and the `_shadow_plan_*`
      persistence.
- [x] **Gate `plan_memory` to skill-only replay** — `_reusable`
      (`plan_memory.py:55`) requires every directive `kind == "SKILL"`;
      `_substitute_count` (`plan_memory.py:97`) also rewrites matching ints in
      `extra`.
- [x] **Fix prod `OLLAMA_URL`** — `~/clustering/manifests/base/minecraft/
      agent.yaml` prod `agent-config` secret: `ollama.mindcraft` →
      `ollama-l3.minecraft-test.svc.cluster.local:11434`.
- [x] **Proof — headless** — `python3 -m py_compile agent.py plan_memory.py`
      (PY_COMPILE_OK); a `plan_memory` unit check asserting `_reusable`
      accepts a SKILL-only plan and rejects a MINE/SMELT plan, and that
      `_substitute_count` rewrites `extra.count` (PLAN_MEMORY_CHECK_OK);
      `yaml` parse of `agent.yaml` (YAML_OK, 10 docs, prod OLLAMA_URL
      confirmed repointed).
