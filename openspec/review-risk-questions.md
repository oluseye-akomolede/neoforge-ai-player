# Review-risk questions (neoforge-ai-player)

Answer each from the diff alone. Any "yes" means the change is risky and gets a full review.
Otherwise it gets a simple review.

1. Does it change how a bot takes or gives items (vault, ME/AE2 storage, chests, STORE_ALL, trading)?
   Why: bugs here destroy or duplicate player items.
2. Does it delete, overwrite or migrate saved data (bot-state JSON, `world/` files, pgvector memory, terrain or container DBs)?
   Why: lost bot or world state can't be regenerated.
3. Does it change who a bot obeys, or what a player can make a bot do (addressing, sender checks, op/permission checks, commands)?
   Why: one player could take over or grief with another player's bots.
4. Does it let a bot break, place or change blocks in new places or in new ways (digging, building, portals, explosives)?
   Why: world damage on the live server is hard to undo.
5. Does it change combat or targeting (what a bot attacks, PvP, friendly fire)?
   Why: bots hurting players or pets is the worst visible failure.
6. Does it change the "stop" / cancel path, or how a plan finishes (orchestrator, finalize, reset)?
   Why: players must always be able to halt a bot, and "done" must be true.
7. Does it change the L3 prompts, the model name, or the JSON the planner expects (l3_planner, plan_schema)?
   Why: one prompt or schema slip breaks every bot's planning at once.
8. Does it change the mod's HTTP API (endpoints, request or response shapes) or the agent's calls to it?
   Why: the agent and the jar ship separately; a mismatch breaks prod quietly.
9. Does it add or change a network call to anything outside the cluster, or touch keys, tokens or secrets?
   Why: leaked credentials or unexpected outbound traffic.
10. Does it change the Dockerfile, build files (Gradle, requirements), Kubernetes manifests or resource limits?
    Why: a bad build or limit takes the server or agent down; limits also touch shared GPUs.
11. Does it make a loop, poll or retry faster, unbounded or parallel (tick handlers, chat poll, L3 calls)?
    Why: server lag, or the shared model's GPUs saturate for every rig.
12. Does it remove or weaken a test, or mark a spec scenario as not required?
    Why: it hides a regression instead of fixing it.
