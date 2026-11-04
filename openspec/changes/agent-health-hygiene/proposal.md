# Agent health hygiene — stop leaking the key to the probe port, make the timeout real

## Why

Two defects in the agent's health path, both introduced by `health-tick-heartbeat`
(shipped to prod 2026-11-04) and both found by the reviewer after the gate:

1. **The agent sends its API key to a listener that ignores it.** `health()`
   (`agent/api.py:48`) calls `_headers()`, which sets `X-Api-Key` from the live,
   shared, rotated `MOD_API_KEY` (`agent/api.py:5-8`), and sends that to the
   dedicated probe port. The comment on that same call records that the probe port
   ignores the beacon headers, and `HealthProbeListener` has no apiKey/auth/header
   reference at all. Same host today, so this is not an active exposure — but it is
   a credential crossing a port boundary into a component with no auth check.
   Whoever next changes that listener, forwards the port, or puts it on a shared
   network inherits the exposure without knowing it exists.

2. **The retry budget's constant does not exist.** The comment at
   `agent/agent.py:4139` says "Each attempt costs up to HEALTH_TIMEOUT (10 s)", but
   `git grep HEALTH_TIMEOUT -- agent/` finds exactly one hit: that comment. There
   is no definition and no import; the 10 is a bare literal at `api.py:48`. A reader
   who tunes the budget from the comment finds nothing, and if they add a constant
   it will silently not take effect because the loop reads the literal. That is the
   silent-no-op class this repo keeps getting bitten by.

Neither is a behaviour change to the health path: one drops a header, the other
makes an existing value addressable. Both are cheap and neither needs a deploy.

## What changes

- `health()` sends the beacon headers **without** `X-Api-Key`. `X-Agent-Id` stays:
  it is the presence beacon the overlay reads, and dropping it would make a healthy
  agent show as "agent down".
- The health timeout becomes a real, named setting with the same default (10 s), read
  by both the call site and anything that documents the budget. Default MUST stay 10
  so this change cannot alter retry arithmetic in production.

## Impact

- Affected spec: `api-http` (the agent readiness requirement from the parent change)
- Affected code: `agent/api.py`, `agent/agent.py` (comment), `agent/config.py` (setting)
- No deploy is required by the lead's scope note; this is spec + code with tests.

## Out of scope

- Re-tuning the retry budget in either direction. This makes the existing value real
  and addressable; it does not change what it is.
- The `.pre-health` rollback jar still in the prod bucket (tracked separately).
