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
 * Each bot is assigned a sector of the cube via bot_index/bot_count in the directive extra params.
 * The cube expands in shells from the center until the target is found or max radius is reached.
 *
 * L3 composable: an LLM can issue WIDE_SEARCH to multiple bots with different bot_index values.
 */
public class WideSearchBehavior implements Behavior {
    private enum Phase {
        PATHING_TO_SECTOR, SCANNING, FOUND_PATHING, EXPANDING, DONE
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
    private int shellIndex;

    private int sectorMinX, sectorMaxX, sectorMinZ, sectorMaxZ;
    private int scanY;
    private int scanX, scanZ;
    private boolean scanComplete;

    private BlockPos foundPos;
    private String foundId;

    // Movement
    private Vec3 moveTarget;
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;

    private int scanTickBudget;
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
                + " center=" + center.toShortString() + " bot " + (botIndex + 1) + "/" + botCount);
        bot.systemChat("Search: " + searchTarget + " [bot " + (botIndex + 1) + "/" + botCount + "]", "aqua");

        computeSectorAndBegin();
    }

    private void computeSectorAndBegin() {
        int radius = SHELL_RADII[Math.min(shellIndex, SHELL_RADII.length - 1)];
        radius = Math.min(radius, maxRadius);

        int diameterX = radius * 2;
        int sliceWidth = Math.max(1, diameterX / botCount);
        sectorMinX = center.getX() - radius + botIndex * sliceWidth;
        sectorMaxX = (botIndex == botCount - 1)
                ? center.getX() + radius
                : sectorMinX + sliceWidth - 1;
        sectorMinZ = center.getZ() - radius;
        sectorMaxZ = center.getZ() + radius;

        scanY = center.getY();
        scanX = sectorMinX;
        scanZ = sectorMinZ;
        scanComplete = false;
        scanTickBudget = 0;

        Vec3 sectorCenter = new Vec3(
                (sectorMinX + sectorMaxX) / 2.0, center.getY(), (sectorMinZ + sectorMaxZ) / 2.0);
        moveTarget = sectorCenter;
        navTicks = 0;

        progress.setPhase("pathing_to_sector");
        progress.logEvent("Shell " + (shellIndex + 1) + ": radius=" + radius
                + " sector X=[" + sectorMinX + "," + sectorMaxX + "]");
        phase = Phase.PATHING_TO_SECTOR;
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (phase == Phase.DONE) {
            if (foundPos != null) {
                return BehaviorResult.SUCCESS;
            }
            return progress.toMap().containsKey("failure_reason")
                    ? BehaviorResult.FAILED : BehaviorResult.SUCCESS;
        }

        return switch (phase) {
            case PATHING_TO_SECTOR -> tickPathing(bot);
            case SCANNING -> tickScanning(bot);
            case FOUND_PATHING -> tickFoundPathing(bot);
            case EXPANDING -> tickExpanding(bot);
            default -> BehaviorResult.RUNNING;
        };
    }

    private BehaviorResult tickPathing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Vec3 pos = player.position();
        double dist = pos.distanceTo(moveTarget);
        navTicks++;

        if (dist < 8.0 || navTicks > NAV_TIMEOUT) {
            phase = Phase.SCANNING;
            progress.setPhase("scanning");
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

    private BehaviorResult tickScanning(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        if ("entity".equalsIgnoreCase(searchType)) {
            return tickEntityScan(bot, player, level);
        }

        int blocksThisTick = 0;
        int minY = level.getMinBuildHeight();
        int maxY = level.getMaxBuildHeight();

        while (blocksThisTick < BLOCKS_PER_TICK && !scanComplete) {
            BlockPos pos = new BlockPos(scanX, scanY, scanZ);

            if (scanY >= minY && scanY <= maxY) {
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
            }

            blocksThisTick++;
            progress.increment("blocks_scanned");

            scanY++;
            if (scanY > Math.min(center.getY() + currentShellRadius(), maxY)) {
                scanY = Math.max(center.getY() - currentShellRadius(), minY);
                scanZ++;
                if (scanZ > sectorMaxZ) {
                    scanZ = sectorMinZ;
                    scanX++;
                    if (scanX > sectorMaxX) {
                        scanComplete = true;
                    }
                }
            }
        }

        if (scanComplete) {
            phase = Phase.EXPANDING;
            progress.setPhase("expanding");
        }

        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickEntityScan(BotPlayer bot, ServerPlayer player, ServerLevel level) {
        double r = currentShellRadius();
        AABB searchBox = new AABB(
                sectorMinX, center.getY() - r, sectorMinZ,
                sectorMaxX + 1, center.getY() + r, sectorMaxZ + 1);

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
        phase = Phase.EXPANDING;
        progress.setPhase("expanding");
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
        computeSectorAndBegin();
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

        // Ore variant matching: "iron" matches "deepslate_iron_ore"
        if (qStripped.endsWith("_ore")) {
            String oreBase = qStripped.substring(0, qStripped.length() - 4);
            if (cStripped.contains(oreBase) && cStripped.contains("ore")) return true;
        }

        // Word-level fuzzy: "cow" matches "mooshroom_cow", "diamond sword" matches "diamond_sword"
        String qNorm = qStripped.replace(' ', '_');
        if (cStripped.contains(qNorm)) return true;

        // Levenshtein on stripped names for typo tolerance
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
            case PATHING_TO_SECTOR -> base + " — moving to sector [bot " + (botIndex + 1) + "/" + botCount + "]";
            case SCANNING -> base + " — scanning shell " + (shellIndex + 1) + " (radius " + currentShellRadius() + ")";
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
