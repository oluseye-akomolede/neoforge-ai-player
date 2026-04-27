package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.*;

/**
 * L1 Wide Search behavior — coordinated expanding-cube search across multiple bots.
 *
 * The cube is divided into a grid of cells (CELL_SIZE x CELL_SIZE in XZ).
 * Cells are assigned round-robin across bots, creating an interleaved checkerboard pattern.
 * Each bot paths to its next cell, scans the full Y column, then moves on.
 * The cube expands in shells until the target is found or max radius is reached.
 *
 * L3 composable: an LLM issues WIDE_SEARCH to N bots with bot_index 0..N-1.
 */
public class WideSearchBehavior implements Behavior {
    private enum Phase {
        PATHING_TO_CELL, SCANNING_CELL, FOUND_PATHING, EXPANDING, DONE
    }

    private final ProgressReport progress = new ProgressReport();

    private Phase phase;
    private String searchTarget;
    private String searchType;
    private int botIndex;
    private int botCount;
    private BlockPos center;
    private int maxRadius;

    private static final int[] SHELL_RADII = {32, 64, 128, 256, 512, 1024};
    private static final int CELL_SIZE = 16;
    private int shellIndex;

    // Cell grid for current shell
    private List<int[]> myCells;
    private int cellIdx;

    // Current cell scan state
    private int cellOriginX, cellOriginZ;
    private int scanX, scanZ, scanY;
    private boolean cellScanDone;

    private BlockPos foundPos;
    private String foundId;

    // Movement
    private Vec3 moveTarget;
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;

    private static final int BLOCKS_PER_TICK = 2048;
    private static final double SPRINT_SPEED = 0.4;
    private static final double FLY_SPEED = 0.8;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final int NAV_TIMEOUT = 600;
    private int navTicks;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();

        searchTarget = directive.getTarget();
        if (searchTarget == null || searchTarget.isBlank()) {
            progress.setFailureReason("No search target specified");
            phase = Phase.DONE;
            return;
        }

        Map<String, String> extra = directive.getExtra();
        searchType = extra.getOrDefault("search_type", "block");
        botIndex = parseIntOr(extra.get("bot_index"), 0);
        botCount = parseIntOr(extra.get("bot_count"), 1);
        maxRadius = directive.getRadius() > 0 ? directive.getRadius() : 512;

        if (directive.hasLocation()) {
            center = new BlockPos((int) directive.getX(), (int) directive.getY(), (int) directive.getZ());
        } else {
            center = bot.getPlayer().blockPosition();
        }

        shellIndex = 0;
        yVelocity = 0;
        ticksStuck = 0;
        lastPos = null;
        foundPos = null;
        foundId = null;

        progress.logEvent("Wide search: target=" + searchTarget + " type=" + searchType
                + " center=" + center.toShortString() + " bot " + (botIndex + 1) + "/" + botCount
                + " cell_size=" + CELL_SIZE);
        bot.systemChat("Search: " + searchTarget + " [bot " + (botIndex + 1) + "/" + botCount + "]", "aqua");

        beginShell();
    }

    private void beginShell() {
        int radius = SHELL_RADII[Math.min(shellIndex, SHELL_RADII.length - 1)];
        radius = Math.min(radius, maxRadius);

        int minX = center.getX() - radius;
        int maxX = center.getX() + radius;
        int minZ = center.getZ() - radius;
        int maxZ = center.getZ() + radius;

        // Build cell grid and assign round-robin
        List<int[]> allCells = new ArrayList<>();
        for (int cx = minX; cx <= maxX; cx += CELL_SIZE) {
            for (int cz = minZ; cz <= maxZ; cz += CELL_SIZE) {
                allCells.add(new int[]{cx, cz});
            }
        }

        myCells = new ArrayList<>();
        for (int i = botIndex; i < allCells.size(); i += botCount) {
            myCells.add(allCells.get(i));
        }

        cellIdx = 0;
        progress.logEvent("Shell " + (shellIndex + 1) + ": radius=" + radius
                + " total_cells=" + allCells.size() + " my_cells=" + myCells.size());

        if (myCells.isEmpty()) {
            phase = Phase.EXPANDING;
            progress.setPhase("expanding");
            return;
        }

        startNextCell();
    }

    private void startNextCell() {
        if (cellIdx >= myCells.size()) {
            phase = Phase.EXPANDING;
            progress.setPhase("expanding");
            return;
        }

        int[] cell = myCells.get(cellIdx);
        cellOriginX = cell[0];
        cellOriginZ = cell[1];
        scanX = cellOriginX;
        scanZ = cellOriginZ;
        scanY = -9999;
        cellScanDone = false;

        moveTarget = new Vec3(cellOriginX + CELL_SIZE / 2.0, center.getY(), cellOriginZ + CELL_SIZE / 2.0);
        navTicks = 0;
        phase = Phase.PATHING_TO_CELL;
        progress.setPhase("pathing_to_cell");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (phase == Phase.DONE) {
            if (foundPos != null) return BehaviorResult.SUCCESS;
            return progress.toMap().containsKey("failure_reason")
                    ? BehaviorResult.FAILED : BehaviorResult.SUCCESS;
        }

        return switch (phase) {
            case PATHING_TO_CELL -> tickPathingToCell(bot);
            case SCANNING_CELL -> tickScanningCell(bot);
            case FOUND_PATHING -> tickFoundPathing(bot);
            case EXPANDING -> tickExpanding(bot);
            default -> BehaviorResult.RUNNING;
        };
    }

    private BehaviorResult tickPathingToCell(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Vec3 pos = player.position();
        double dist = pos.distanceTo(moveTarget);
        navTicks++;

        if (dist < 12.0 || navTicks > NAV_TIMEOUT) {
            phase = Phase.SCANNING_CELL;
            progress.setPhase("scanning_cell");
            return BehaviorResult.RUNNING;
        }

        moveToward(bot, player, moveTarget, dist);
        return BehaviorResult.RUNNING;
    }

    private static final Set<String> NOTABLE_BLOCKS = Set.of(
            "ore", "chest", "barrel", "spawner", "ancient_debris", "obsidian",
            "diamond", "emerald", "lapis", "redstone", "gold", "iron",
            "amethyst", "sculk_sensor", "sculk_shrieker", "end_portal_frame"
    );

    private static boolean isNotable(String blockId) {
        String stripped = blockId.contains(":") ? blockId.substring(blockId.indexOf(':') + 1) : blockId;
        for (String keyword : NOTABLE_BLOCKS) {
            if (stripped.contains(keyword)) return true;
        }
        return false;
    }

    private BehaviorResult tickScanningCell(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        if ("entity".equalsIgnoreCase(searchType)) {
            return tickEntityScan(bot, player, level);
        }

        int minY = level.getMinBuildHeight();
        int maxY = level.getMaxBuildHeight();

        if (scanY == -9999) {
            scanX = cellOriginX;
            scanZ = cellOriginZ;
            scanY = minY;
        }

        int cellEndX = cellOriginX + CELL_SIZE;
        int cellEndZ = cellOriginZ + CELL_SIZE;
        int blocksThisTick = 0;

        while (blocksThisTick < BLOCKS_PER_TICK && !cellScanDone) {
            BlockPos pos = new BlockPos(scanX, scanY, scanZ);

            if (!level.getBlockState(pos).isAir()) {
                String blockId = BuiltInRegistries.BLOCK.getKey(level.getBlockState(pos).getBlock()).toString();

                if (isNotable(blockId)) {
                    progress.recordBlock(pos.getX(), pos.getY(), pos.getZ(), blockId);
                    progress.increment("notable_blocks");
                }

                if (fuzzyMatch(blockId, searchTarget)) {
                    onFound(bot, pos, blockId);
                    return BehaviorResult.RUNNING;
                }
            }

            blocksThisTick++;
            progress.increment("blocks_scanned");

            scanY++;
            if (scanY > maxY) {
                scanY = minY;
                scanZ++;
                if (scanZ >= cellEndZ) {
                    scanZ = cellOriginZ;
                    scanX++;
                    if (scanX >= cellEndX) {
                        cellScanDone = true;
                    }
                }
            }
        }

        if (cellScanDone) {
            cellIdx++;
            progress.increment("cells_completed");
            startNextCell();
        }

        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickEntityScan(BotPlayer bot, ServerPlayer player, ServerLevel level) {
        double r = currentShellRadius();
        AABB searchBox = new AABB(
                cellOriginX, center.getY() - r, cellOriginZ,
                cellOriginX + CELL_SIZE, center.getY() + r, cellOriginZ + CELL_SIZE);

        for (Entity entity : level.getEntities(player, searchBox)) {
            if (!(entity instanceof LivingEntity le)) continue;
            if (!le.isAlive()) continue;
            if (entity instanceof ServerPlayer) continue;

            String typeId = entity.getType().toShortString().toLowerCase();
            String name = entity.getName().getString().toLowerCase();

            if (fuzzyMatch(typeId, searchTarget) || fuzzyMatch(name, searchTarget)) {
                BlockPos ePos = entity.blockPosition();
                onFound(bot, ePos, typeId + " '" + name + "'");
                return BehaviorResult.RUNNING;
            }
        }

        progress.increment("entity_scans");
        cellIdx++;
        progress.increment("cells_completed");
        startNextCell();
        return BehaviorResult.RUNNING;
    }

    private void onFound(BotPlayer bot, BlockPos pos, String id) {
        foundPos = pos;
        foundId = id;
        progress.logEvent("FOUND: " + id + " at " + pos.toShortString());
        progress.increment("targets_found");
        bot.systemChat("Found " + id + " at " + pos.toShortString(), "green");

        moveTarget = Vec3.atCenterOf(pos);
        navTicks = 0;
        phase = Phase.FOUND_PATHING;
        progress.setPhase("found_pathing");
    }

    private BehaviorResult tickFoundPathing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Vec3 pos = player.position();
        double dist = pos.distanceTo(moveTarget);
        navTicks++;

        if (dist < 4.0 || navTicks > NAV_TIMEOUT) {
            progress.logEvent("Arrived at target: " + foundId);
            phase = Phase.DONE;
            progress.setPhase("done");
            return BehaviorResult.SUCCESS;
        }

        moveToward(bot, player, moveTarget, dist);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickExpanding(BotPlayer bot) {
        shellIndex++;
        int nextRadius = shellIndex < SHELL_RADII.length
                ? Math.min(SHELL_RADII[shellIndex], maxRadius)
                : maxRadius;
        int prevRadius = SHELL_RADII[Math.min(shellIndex - 1, SHELL_RADII.length - 1)];

        if (nextRadius <= prevRadius || shellIndex >= SHELL_RADII.length) {
            progress.logEvent("Search exhausted at radius " + prevRadius + " — target not found");
            progress.setFailureReason("Target '" + searchTarget + "' not found within " + prevRadius + " blocks");
            bot.systemChat("Search failed: " + searchTarget + " not found", "red");
            phase = Phase.DONE;
            return BehaviorResult.FAILED;
        }

        progress.logEvent("Expanding to shell " + (shellIndex + 1) + " radius=" + nextRadius);
        beginShell();
        return BehaviorResult.RUNNING;
    }

    private int currentShellRadius() {
        return Math.min(SHELL_RADII[Math.min(shellIndex, SHELL_RADII.length - 1)], maxRadius);
    }

    static boolean fuzzyMatch(String candidate, String query) {
        String c = candidate.toLowerCase();
        String q = query.toLowerCase();

        if (c.equals(q) || c.contains(q)) return true;

        String cStripped = c.contains(":") ? c.substring(c.indexOf(':') + 1) : c;
        String qStripped = q.contains(":") ? q.substring(q.indexOf(':') + 1) : q;

        if (cStripped.equals(qStripped) || cStripped.contains(qStripped)) return true;

        if (qStripped.endsWith("_ore")) {
            String oreBase = qStripped.substring(0, qStripped.length() - 4);
            if (cStripped.contains(oreBase) && cStripped.contains("ore")) return true;
        }

        String qNorm = qStripped.replace(' ', '_');
        if (cStripped.contains(qNorm)) return true;

        if (qStripped.length() >= 4 && levenshtein(cStripped, qStripped) <= Math.max(1, qStripped.length() / 4))
            return true;

        return false;
    }

    private static int levenshtein(String a, String b) {
        int[] prev = new int[b.length() + 1];
        int[] curr = new int[b.length() + 1];
        for (int j = 0; j <= b.length(); j++) prev[j] = j;
        for (int i = 1; i <= a.length(); i++) {
            curr[0] = i;
            for (int j = 1; j <= b.length(); j++) {
                int cost = a.charAt(i - 1) == b.charAt(j - 1) ? 0 : 1;
                curr[j] = Math.min(Math.min(curr[j - 1] + 1, prev[j] + 1), prev[j - 1] + cost);
            }
            int[] tmp = prev;
            prev = curr;
            curr = tmp;
        }
        return prev[b.length()];
    }

    private void moveToward(BotPlayer bot, ServerPlayer player, Vec3 target, double dist) {
        Vec3 currentPos = player.position();
        double heightDiff = Math.abs(target.y - currentPos.y);

        if (heightDiff > 4.0) {
            Vec3 dir = target.subtract(currentPos).normalize();
            double moveSpeed = Math.min(FLY_SPEED, dist);
            player.moveTo(
                    currentPos.x + dir.x * moveSpeed,
                    currentPos.y + dir.y * moveSpeed,
                    currentPos.z + dir.z * moveSpeed);
            yVelocity = 0;
            bot.lookAt(target.x, target.y, target.z);
            return;
        }

        Vec3 direction = target.subtract(currentPos).normalize();
        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, direction)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }

        if (lastPos != null && currentPos.distanceTo(lastPos) < 0.01) {
            ticksStuck++;
            if (ticksStuck > 20) {
                player.moveTo(currentPos.x + direction.x * 2.0, currentPos.y + 1.0,
                        currentPos.z + direction.z * 2.0);
                yVelocity = 0;
                ticksStuck = 0;
            }
        } else {
            ticksStuck = 0;
        }
        lastPos = currentPos;

        player.move(MoverType.SELF, new Vec3(direction.x * SPRINT_SPEED, yVelocity, direction.z * SPRINT_SPEED));
        bot.lookAt(target.x, target.y, target.z);
    }

    private static int parseIntOr(String val, int def) {
        if (val == null) return def;
        try { return Integer.parseInt(val); }
        catch (NumberFormatException e) { return def; }
    }

    @Override
    public String describeState() {
        String base = "Wide search for " + searchTarget;
        return switch (phase) {
            case PATHING_TO_CELL -> base + " — moving to cell " + (cellIdx + 1)
                    + "/" + (myCells != null ? myCells.size() : "?")
                    + " [bot " + (botIndex + 1) + "/" + botCount + "]";
            case SCANNING_CELL -> base + " — scanning cell " + (cellIdx + 1)
                    + " (shell " + (shellIndex + 1) + ", radius " + currentShellRadius() + ")";
            case FOUND_PATHING -> base + " — found " + foundId + ", moving to it";
            case EXPANDING -> base + " — expanding search";
            case DONE -> foundPos != null
                    ? base + " — found at " + foundPos.toShortString()
                    : base + " — not found";
        };
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {
        phase = Phase.DONE;
    }
}
