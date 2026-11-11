## 1. Spec

- [x] Proposal written (`proposal.md`), covering both defects and naming the two items left out of scope
- [x] Delta against `api-http`: MODIFIED "Agent Health Readiness Survives The Port Move", carrying all
      5 existing scenarios forward plus 4 new ones (no-key, bot-calls-still-authenticate, named setting,
      tuning-takes-effect). Omission-by-name is a removal, so the block is copied whole.
- [x] `openspec validate agent-health-hygiene --strict` passes with no omitted-scenario warning
- [ ] Reviewer reads the spec before any code is written

## 2. Code — drop X-Api-Key from the health call

- [x] `agent/api.py`: add a beacon-only header helper beside `_headers()` that sets `Content-Type` and
      `X-Agent-Id` but never `X-Api-Key`
- [x] `agent/api.py:48`: `health()` uses the beacon-only helper
- [x] Confirm the presence beacon still reaches the overlay: `X-Agent-Id` MUST still be set, dropping
      it would make a healthy agent show as "agent down"
- [x] Confirm every other call still sends `X-Api-Key` (`_headers()` untouched)
- [x] `git grep -n "X-Api-Key" agent/` and account for every remaining hit

## 3. Code — make the health timeout a real setting

- [x] `agent/config.py`: add the timeout setting, default 10, resolved the way the file's other
      settings are (env, then default)
- [x] `agent/api.py:48`: the call site reads the setting instead of the literal `10`
- [x] `agent/agent.py:4139`: the retry-budget comment names the setting by the name the code reads,
      not a constant that does not exist
- [x] `git grep -n "HEALTH_TIMEOUT" agent/` — either every hit is a real definition/read, or the
      name is gone and the comment says the setting name instead
- [x] The default MUST remain 10 s, so the retry arithmetic that bounds the startup gate is unchanged

## 4. Tests

- [x] Agent tests pass as the qcode `--check` (`nice -n 19 python3 -m pytest -q agent/tests/...`),
      run bounded: `(ulimit -v 4194304; ...)`, at most 2 workers
- [x] A test that the health request carries `X-Agent-Id` and does not carry `X-Api-Key`
- [x] A test that a bot call still carries `X-Api-Key`
- [x] A test that the timeout setting is honoured and that its default is 10
- [x] Do NOT alter the retry counts (`max_retries = 90`) — this change does not re-tune the budget

## 5. Done

- [ ] Reviewer checks the diff against the delta's scenarios
- [ ] One revision cycle, then stop (lead's scope note); no deploy today
