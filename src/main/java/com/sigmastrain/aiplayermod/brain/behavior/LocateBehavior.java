package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.TempadBridge;
import com.sigmastrain.aiplayermod.world.StructureLookup;
import net.minecraft.core.BlockPos;
import net.minecraft.core.HolderSet;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.levelgen.structure.Structure;
import net.minecraft.world.phys.Vec3;

import java.util.List;

/**
 * L1 LOCATE — ask the world generator where a structure is.
 *
 * <p>Answers "where is the nearest end city / fortress / village" in a single
 * generator query, out to ~1600 blocks by default. This is the capability the
 * End expedition proved missing: {@code WIDE_SEARCH} brute-forces BLOCKS, so it
 * can never find a STRUCTURE no matter how long it runs.
 *
 * <p>By default LOCATE reports coordinates and stops — the planner chains
 * TELEPORT or GOTO from the result, and the coordinates are equally usable as a
 * waypoint. Set {@code extra.travel=true} to land the bot there in one step.
 *
 * <p>The generator query is synchronous and must run on the server thread, so
 * it happens exactly once, on the first tick, and its cost is reported in
 * {@code search_ms} rather than hidden.
 */
public class LocateBehavior implements Behavior {

    private enum Phase { SEARCH, TRAVEL, DONE }

    private final ProgressReport progress = new ProgressReport();

    private Phase phase = Phase.SEARCH;
    private BehaviorResult terminal = BehaviorResult.RUNNING;

    private String target;
    private int chunkRadius;
    private boolean travel;
    private String shareWith;

    private BlockPos foundPos;
    private String foundId;

    private static final int DEFAULT_CHUNK_RADIUS = 100;   // same as /locate
    private static final int MAX_CHUNK_RADIUS = 256;
    private static final int TRAVEL_SEARCH_RADIUS = 16;
    private static final int NO_SPOT = Integer.MIN_VALUE;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("resolving");

        target = directive.getTarget();
        travel = Boolean.parseBoolean(directive.getExtra().getOrDefault("travel", "false"));
        shareWith = directive.getExtra().get("share_with");

        // Radius is in CHUNKS here, unlike every other directive, because that
        // is the unit the generator search takes. Reading the block-radius
        // field would silently shrink a 1600-block search to 16.
        int r = DEFAULT_CHUNK_RADIUS;
        String raw = directive.getExtra().get("chunk_radius");
        if (raw != null) {
            try { r = Integer.parseInt(raw.trim()); } catch (NumberFormatException ignored) {}
        }
        chunkRadius = Math.max(1, Math.min(MAX_CHUNK_RADIUS, r));

        if (target == null || target.isBlank()) {
            finish(BehaviorResult.FAILED, "LOCATE requires a structure name in 'target'");
        }
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case SEARCH -> doSearch(bot);
            case TRAVEL -> doTravel(bot);
            case DONE -> terminal;
        };
    }

    private BehaviorResult doSearch(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        String dimension = level.dimension().location().toString();

        if (!StructureLookup.structuresEnabled(level)) {
            return finish(BehaviorResult.FAILED, "structure generation is disabled on this world");
        }

        // Resolve and dimension-filter in one step. The filter is nearly free
        // and runs FIRST on purpose: "end_city from the Overworld" would
        // otherwise burn a full multi-thousand-chunk search to learn nothing.
        StructureLookup.Resolution res = StructureLookup.resolveInDimension(level, target);
        if (!res.ok()) {
            return finish(BehaviorResult.FAILED, res.error());
        }
        progress.putResult("resolved_by", res.method());
        progress.putResult("candidates", res.matchedIds().size() > 8
                ? res.matchedIds().subList(0, 8) : res.matchedIds());
        progress.increment("candidates", res.matchedIds().size());

        HolderSet<Structure> searchable = res.holders();
        progress.setPhase("searching");
        BlockPos origin = player.blockPosition();
        StructureLookup.Found found = StructureLookup.findNearest(level, searchable, origin, chunkRadius);

        if (found == null) {
            return finish(BehaviorResult.FAILED,
                    "no '" + target + "' within " + chunkRadius + " chunks (~"
                            + (chunkRadius * 16) + " blocks) of " + origin.toShortString()
                            + " in " + dimension);
        }

        foundPos = found.pos();
        foundId = found.structureId();

        progress.increment("search_ms", (int) found.elapsedMs());
        progress.putResult("found", true);
        progress.putResult("structure", foundId);
        progress.putResult("x", foundPos.getX());
        progress.putResult("y", foundPos.getY());
        progress.putResult("z", foundPos.getZ());
        progress.putResult("dimension", dimension);
        progress.putResult("distance", (int) found.distance());
        progress.logEvent("FOUND " + foundId + " at " + foundPos.getX() + "," + foundPos.getZ()
                + " (" + (int) found.distance() + " blocks away, " + found.elapsedMs() + "ms)");

        AIPlayerMod.LOGGER.info("[{}] LOCATE {} -> {} at {} {} ({} blocks, {}ms, radius {} chunks)",
                player.getName().getString(), target, foundId,
                foundPos.getX(), foundPos.getZ(), (int) found.distance(),
                found.elapsedMs(), chunkRadius);
        bot.systemChat("Located " + foundId + " at " + foundPos.getX() + ", " + foundPos.getZ()
                + " (" + (int) found.distance() + " blocks)", "aqua");

        if (!travel) {
            // Share a spot you can stand on, not the generator's reference.
            // Its Y is routinely 0 — a TemPad portal to y=0 in the overworld
            // opens inside bedrock. Resolving costs one chunk generate, which
            // is the price of the waypoint being usable.
            shareToTempad(bot, level, resolveWaypointPos(level, foundPos));
            return finish(BehaviorResult.SUCCESS, null);
        }
        phase = Phase.TRAVEL;
        progress.setPhase("traveling");
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult doTravel(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        // Force the destination chunks to generate BEFORE asking where the
        // ground is. Skipping this reads air for every block in an ungenerated
        // chunk, so safeGroundY finds no pocket and falls back to a fixed
        // height — which put a bot inside a bastion wall above lava.
        int cx = foundPos.getX() >> 4;
        int cz = foundPos.getZ() >> 4;
        for (int dx = -1; dx <= 1; dx++) {
            for (int dz = -1; dz <= 1; dz++) {
                level.getChunk(cx + dx, cz + dz);
            }
        }

        BlockPos landing = findLandingSpot(level, foundPos);
        boolean safe = landing != null;
        if (!safe) {
            // A bastion's reference corner can sit over open lava. Nothing
            // standable nearby is a real outcome, not a reason to pretend the
            // structure wasn't found — put the bot above the column and say so.
            int y = Math.max(BotPlayer.safeGroundY(level, foundPos.getX(), foundPos.getZ(),
                    foundPos.getY()), level.getMinBuildHeight() + 40);
            landing = new BlockPos(foundPos.getX(), y, foundPos.getZ());
        }

        bot.teleport(landing.getX() + 0.5, landing.getY(), landing.getZ() + 0.5);

        progress.putResult("travelled_to_y", landing.getY());
        if (!landing.equals(foundPos)) {
            progress.putResult("landed_at", List.of(landing.getX(), landing.getY(), landing.getZ()));
        }
        if (!safe) progress.putResult("travel_unsafe", true);
        progress.logEvent("Travelled to " + foundId + " at "
                + landing.getX() + "," + landing.getY() + "," + landing.getZ()
                + (safe ? "" : " (no standable ground nearby)"));
        bot.systemChat("Arrived at " + foundId, safe ? "green" : "yellow");

        // Share where the bot actually stands — a position already proven
        // standable beats any re-derivation.
        shareToTempad(bot, level, landing);
        return finish(BehaviorResult.SUCCESS, null);
    }

    /**
     * A standable position for a waypoint the player will portal into.
     *
     * <p>Force-loads the destination chunk for the same reason travel does:
     * an ungenerated chunk reads as air, and a height query over air is a
     * guess. Falls back to the structure column if nothing nearby is standable.
     */
    private static BlockPos resolveWaypointPos(ServerLevel level, BlockPos origin) {
        try {
            level.getChunk(origin.getX() >> 4, origin.getZ() >> 4);
            BlockPos spot = findLandingSpot(level, origin);
            if (spot != null) return spot;
            int y = BotPlayer.safeGroundY(level, origin.getX(), origin.getZ(), origin.getY());
            return new BlockPos(origin.getX(), y, origin.getZ());
        } catch (Exception e) {
            return origin;
        }
    }

    /**
     * Push the finding to a player's TemPad, if one was named.
     *
     * <p>Never fails the directive: the structure WAS located, and a waypoint
     * that could not be delivered does not undo that. The outcome is recorded
     * in the result either way so the planner and the player both know.
     */
    private void shareToTempad(BotPlayer bot, ServerLevel level, BlockPos waypointPos) {
        if (shareWith == null || shareWith.isBlank()) return;

        var server = level.getServer();
        var profile = TempadBridge.resolveProfile(server, shareWith);
        if (profile == null) {
            progress.putResult("shared", false);
            progress.putResult("share_error", "no player named '" + shareWith + "'");
            return;
        }

        String label = TempadBridge.prettyName(foundId);
        String error = TempadBridge.addWaypoint(
                profile, label,
                new Vec3(waypointPos.getX() + 0.5, waypointPos.getY(), waypointPos.getZ() + 0.5),
                level.dimension(),
                TempadBridge.colorFor(foundId));

        if (error == null) {
            progress.putResult("shared", true);
            progress.putResult("shared_with", profile.getName());
            progress.putResult("waypoint_y", waypointPos.getY());
            progress.logEvent("Waypoint '" + label + "' sent to " + profile.getName() + "'s TemPad");
            bot.systemChat("Waypoint sent to " + profile.getName() + "'s TemPad: "
                    + label + " (" + waypointPos.getX() + ", " + waypointPos.getZ() + ")", "light_purple");
            var online = server.getPlayerList().getPlayerByName(profile.getName());
            if (online != null) {
                online.sendSystemMessage(net.minecraft.network.chat.Component.literal(
                        "[" + bot.getPlayer().getName().getString() + "] Waypoint added to your TemPad: "
                                + label + " at " + waypointPos.getX() + ", " + waypointPos.getY()
                                + ", " + waypointPos.getZ()
                                + " (" + level.dimension().location() + ")"));
            }
        } else {
            progress.putResult("shared", false);
            progress.putResult("share_error", error);
            bot.systemChat("Could not reach " + profile.getName() + "'s TemPad: " + error, "yellow");
        }
    }

    /**
     * A place to actually stand near the structure, or null.
     *
     * <p>The generator's position is a bounding-box reference, not a doorstep:
     * for a bastion it is routinely open lava. Structures are big, so search
     * outward in rings rather than insisting on that one column.
     */
    private static BlockPos findLandingSpot(ServerLevel level, BlockPos origin) {
        for (int ring = 0; ring <= TRAVEL_SEARCH_RADIUS; ring += 4) {
            for (int dx = -ring; dx <= ring; dx += 4) {
                for (int dz = -ring; dz <= ring; dz += 4) {
                    // Only the perimeter of each ring — the interior was covered already.
                    if (ring > 0 && Math.abs(dx) != ring && Math.abs(dz) != ring) continue;
                    int x = origin.getX() + dx;
                    int z = origin.getZ() + dz;
                    int startY = BotPlayer.safeGroundY(level, x, z, origin.getY());
                    int y = firstStandableAt(level, x, startY, z);
                    if (y != NO_SPOT) return new BlockPos(x, y, z);
                }
            }
        }
        return null;
    }

    /**
     * Nearest y at or above {@code startY} with two air blocks over solid,
     * non-fluid ground, or {@link #NO_SPOT}. Structures are buildings: the
     * heightmap answer can be a roof, a wall, or the surface of a lava lake the
     * structure straddles. Requires the chunk to be loaded — see the caller.
     */
    private static int firstStandableAt(ServerLevel level, int x, int startY, int z) {
        int top = Math.min(level.getMaxBuildHeight() - 2, startY + 48);
        var pos = new BlockPos.MutableBlockPos();
        for (int y = Math.max(level.getMinBuildHeight() + 1, startY); y <= top; y++) {
            pos.set(x, y, z);
            boolean feetClear = level.getBlockState(pos).isAir();
            pos.set(x, y + 1, z);
            boolean headClear = level.getBlockState(pos).isAir();
            pos.set(x, y - 1, z);
            var below = level.getBlockState(pos);
            boolean groundOk = below.isSolid() && level.getFluidState(pos).isEmpty();
            if (feetClear && headClear && groundOk) return y;
        }
        return NO_SPOT;
    }

    private BehaviorResult finish(BehaviorResult result, String failureReason) {
        phase = Phase.DONE;
        terminal = result;
        progress.setPhase(result == BehaviorResult.SUCCESS ? "done" : "failed");
        if (failureReason != null) {
            progress.setFailureReason(failureReason);
            progress.putResult("found", false);
        }
        return result;
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case SEARCH -> "Locating " + target + " (radius " + chunkRadius + " chunks)";
            case TRAVEL -> "Travelling to " + foundId + " at "
                    + foundPos.getX() + "," + foundPos.getZ();
            case DONE -> foundPos != null
                    ? "Located " + foundId + " at " + foundPos.getX() + "," + foundPos.getZ()
                    : "Locate " + target + " — not found";
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {
        phase = Phase.DONE;
    }
}
