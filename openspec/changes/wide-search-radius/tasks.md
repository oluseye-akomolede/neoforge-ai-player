## 1. Spec
- [x] 1.1 Write the proposal and spec deltas (MODIFIED Escalating Search, ADDED Wide Search Radius)
- [x] 1.2 Validate with `openspec validate wide-search-radius --strict`
- [x] 1.3 Confirm the MODIFIED delta carries every live scenario

## 2. Behavior
- [ ] 2.1 Read `extra.radius`, falling back to the top-level radius, clamped [1, ceiling]
- [ ] 2.2 Keep the default path byte-identical: no radius means 32 first shell, escalation to 256
- [ ] 2.3 Report the radius actually searched on the failure path

## 3. Surfaces
- [ ] 3.1 Advertise `radius` on the `goto_and_scan` seed
- [ ] 3.2 Advertise `radius` in the L3 directive vocabulary

## 4. Tests
- [ ] 4.1 Small radius scans 1 cell, not the 25-cell sweep
- [ ] 4.2 `extra.radius` overrides the top-level field
- [ ] 4.3 No radius preserves the 25-cell first shell
- [ ] 4.4 Failure message states the searched radius, not 32
- [ ] 4.5 Each test red with the fix removed

## 5. Verify
- [ ] 5.1 Mod tests pass under the JVM exception (no ulimit -v)
- [ ] 5.2 Agent tests still pass
- [ ] 5.3 Commit on ship-ca27-harness
