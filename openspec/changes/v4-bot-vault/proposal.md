# v4: Bot Vault — unbounded per-bot storage

## Why

A bot's 36 carried slots were treated as its total holdings, so a full
inventory was a hard failure boundary. Deliveries silently evaporated
(findings 16, 27), and the mitigation — dropping at the bot's feet — is
actively destructive: the `entity-cleanup` cronjob runs
`kill @e[type=item]` every 10 minutes.

The fix is to stop treating carried slots as holdings. The 36 slots
become a **working set**; an unbounded per-bot **vault** is the backing
store, and the mod pages between them transparently.

## Design

**Capacity is unbounded and free** (user directive). Storage scarcity is
not an interesting constraint in a world where bots conjure matter from
XP, and every bounded design re-introduces the failure class this change
exists to remove.

- `BotVault` — stacks merged on insert, kept at or below max stack size,
  persisted per bot in the profile JSON. Survives restarts and death.
- `BotPlayer.deliver(stack)` — carried first, overflow to vault. Never
  drops, never evaporates. Used by CHANNEL, MINE, CRAFT, and combat loot.
- `BotPlayer.flushToVault(slots, pinned)` — retention policy: never evict
  equipped gear, tools, the active directive's material, or one food
  stack; largest stacks go first.
- `BotPlayer.ensureCarried(item, n)` — pages material back in on demand;
  BUILD calls it before failing "out of X".

## The critical seam

**Criteria and provisioning MUST count carried + vault.** A criterion
checking only carried slots fails bots that did the work correctly and
paged the results away — the exact bug class of findings 13/25/27.

- `/bot/{name}/effective_inventory` returns per-item `carried`, `vault`,
  and `count`.
- `criteria_eval` inventory clauses read effective holdings.
- `_provision_materials` subtracts effective holdings before channeling.
- World-state summaries report vault contents so L3 plans knowing what
  it already owns.

## What Changes

- **api-http**: new `vault`, `vault_search`, `effective_inventory`,
  `vault_store`, `vault_withdraw` actions on `/bot/{name}/`.
- **bot-inventory**: carried slots are a working set over an unbounded
  vault; overflow paging and retention policy are mod-side and automatic.
- **l3-spec-driven-planning**: `VAULT_STORE` / `VAULT_WITHDRAW`
  directives (aliases: STORE/STASH/DEPOSIT, WITHDRAW/RETRIEVE); DROP
  demoted to "destroys items — prefer VAULT_STORE"; inventory criteria
  count carried + vault.
- **dashboard**: holdings panel (carried vs vault, per-item stow and
  withdraw, search), fleet-wide "who has X" endpoint, and item chips in
  the command bar so instructions name items the bot actually holds.

## Non-Goals

- No XP cost or upkeep for vault storage (user directive).
- Physical container infrastructure (`CONTAINER_*`, `ContainerRegistry`)
  is untouched — it remains the shared/base storage layer. The vault is
  personal and always-available.
