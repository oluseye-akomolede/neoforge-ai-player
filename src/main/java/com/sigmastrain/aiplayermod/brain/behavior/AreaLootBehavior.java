package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.ClavisBridge;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.entity.RandomizableContainerBlockEntity;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Loot-all area behavior — the replacement for the old targeted
 * CONTAINER_SEARCH. There is no "target item": the bot enumerates every
 * spawnable container in a cube around a center, rolls its loot table (or
 * unlocks its Clavis lock first), and drains every stack into the bot (carried
 * inventory, then vault). The trailing STORE_ALL in the skill then pages it all
 * into the ME network.
 *
 * <p>Survey is enumeration, not block-by-block WIDE_SEARCH scanning: the cube is
 * walked once (budgeted per tick so a large radius never freezes the server
 * thread), collecting lootable positions — Clavis-locked containers, unopened
 * loot-table containers, and opened containers that still hold items. The list
 * is sharded round-robin by {@code bot_index}/{@code bot_count}, so N units each
 * take every Nth container and the whole area is drained with no overlap.
 *
 * <p>Center resolves from the directive location, else an {@code extra}
 * x/y/z triple (how the skill passes a "marked area"), else the bot's own
 * position. Radius defaults to {@value #DEFAULT_RADIUS} and is hard-capped at
 * {@value #MAX_RADIUS} — a cube that size is already millions of blocks; the
 * area is meant to be a room or a structure, not a biome.
 */
public class AreaLootBehavior implements Behavior {

    private enum Phase { SURVEY, LOOTING, DONE }

    private static final int DEFAULT_RADIUS = 32;
    private static final int MAX_RADIUS = 64;
    private static final int SURVEY_BLOCKS_PER_TICK = 4096;

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private BlockPos center;
    private int radius;
    private int botIndex;
    private int botCount;

    // Survey cursor + bounds
    private int minX, maxX, minY, maxY, minZ, maxZ;
    private int scanX, scanY, scanZ;
    private final List<BlockPos> surveyed = new ArrayList<>();

    // My shard of the survey, drained in order
    private List<BlockPos> targets = List.of();
    private int index;
    private int containersLooted;
    private int itemsLooted;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        Map<String, String> extra = directive.getExtra();

        botIndex = parseIntOr(extra.get("bot_index"), 0);
        botCount = Math.max(1, parseIntOr(extra.get("bot_count"), 1));
        radius = Math.max(1, Math.min(parseIntOr(extra.get("radius"), DEFAULT_RADIUS), MAX_RADIUS));

        center = resolveCenter(bot, directive, extra);
        ServerLevel level = bot.getPlayer().serverLevel();

        minX = center.getX() - radius; maxX = center.getX() + radius;
        minY = Math.max(level.getMinBuildHeight(), center.getY() - radius);
        maxY = Math.min(level.getMaxBuildHeight(), center.getY() + radius);
        minZ = center.getZ() - radius; maxZ = center.getZ() + radius;
        scanX = minX; scanY = minY; scanZ = minZ;

        containersLooted = 0;
        itemsLooted = 0;
        phase = Phase.SURVEY;

        progress.logEvent("Area loot: center=" + center.toShortString() + " radius=" + radius
                + " bot " + (botIndex + 1) + "/" + botCount);
        bot.systemChat("Looting area around " + center.toShortString() + " [bot "
                + (botIndex + 1) + "/" + botCount + "]", "aqua");
        AIPlayerMod.LOGGER.info("[{}] AREA_LOOT survey: center={} radius={} bot {}/{}",
                bot.getPlayer().getName().getString(), center.toShortString(), radius,
                botIndex + 1, botCount);
    }

    private static BlockPos resolveCenter(BotPlayer bot, Directive directive, Map<String, String> extra) {
        if (directive.hasLocation()) {
            return new BlockPos((int) directive.getX(), (int) directive.getY(), (int) directive.getZ());
        }
        int x = parseIntOr(extra.get("x"), Integer.MIN_VALUE);
        int y = parseIntOr(extra.get("y"), Integer.MIN_VALUE);
        int z = parseIntOr(extra.get("z"), Integer.MIN_VALUE);
        if (x != Integer.MIN_VALUE && y != Integer.MIN_VALUE && z != Integer.MIN_VALUE) {
            return new BlockPos(x, y, z);
        }
        return bot.getPlayer().blockPosition();
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case SURVEY -> tickSurvey(bot);
            case LOOTING -> tickLooting(bot);
            case DONE -> progress.toMap().containsKey("failure_reason")
                    ? BehaviorResult.FAILED : BehaviorResult.SUCCESS;
        };
    }

    private BehaviorResult tickSurvey(BotPlayer bot) {
        ServerLevel level = bot.getPlayer().serverLevel();
        ServerPlayer player = bot.getPlayer();
        boolean clavis = ClavisBridge.isAvailable();

        int budget = SURVEY_BLOCKS_PER_TICK;
        while (budget-- > 0 && scanY <= maxY) {
            BlockPos p = new BlockPos(scanX, scanY, scanZ);

            BlockEntity be = level.getBlockEntity(p);
            if (be instanceof Container c) {
                boolean keep;
                if (clavis && ClavisBridge.isLocked(level, player, p)) {
                    keep = true;                       // sealed — unlock will roll it
                } else if (be instanceof RandomizableContainerBlockEntity) {
                    keep = true;                       // unopened loot table or already-rolled
                } else {
                    keep = hasAnyItem(c);              // ordinary container with something in it
                }
                if (keep) surveyed.add(p);
            }

            scanY++;
            if (scanY > maxY) {
                scanY = minY;
                scanZ++;
                if (scanZ > maxZ) {
                    scanZ = minZ;
                    scanX++;
                }
            }
        }

        if (scanY <= maxY) {
            return BehaviorResult.RUNNING;             // still surveying
        }

        // Survey complete — shard round-robin and start draining.
        targets = new ArrayList<>();
        for (int i = botIndex; i < surveyed.size(); i += botCount) {
            targets.add(surveyed.get(i));
        }
        index = 0;
        progress.logEvent("Surveyed " + surveyed.size() + " lootable containers, my share=" + targets.size());
        if (targets.isEmpty()) {
            phase = Phase.DONE;
            progress.logEvent("Nothing to loot in area");
            bot.systemChat("Nothing to loot in this area", "yellow");
            return BehaviorResult.SUCCESS;
        }
        phase = Phase.LOOTING;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickLooting(BotPlayer bot) {
        if (index >= targets.size()) {
            return finish(bot);
        }

        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockPos p = targets.get(index);
        index++;

        // Step the bot to the container so the drain is visible in-world, then
        // roll + drain the block entity directly (purely server-side).
        player.teleportTo(level, p.getX() + 0.5, p.getY(), p.getZ() + 0.5, player.getYRot(), player.getXRot());
        bot.lookAt(p.getX() + 0.5, p.getY() + 0.5, p.getZ() + 0.5);

        lootAt(bot, level, player, p);
        containersLooted++;
        progress.setPhase("looting " + index + "/" + targets.size());

        if (index >= targets.size()) {
            return finish(bot);
        }
        return BehaviorResult.RUNNING;
    }

    /** Roll any sealed/unopened loot and drain every stack into the bot. */
    private void lootAt(BotPlayer bot, ServerLevel level, ServerPlayer player, BlockPos p) {
        BlockEntity be = level.getBlockEntity(p);

        if (ClavisBridge.isAvailable() && ClavisBridge.isLocked(level, player, p)) {
            for (Object lock : ClavisBridge.getLocksAt(level, player, p)) {
                ClavisBridge.unlockWithQuality(level, player, p, lock, ClavisBridge.maxQuality());
            }
        }
        if (be instanceof RandomizableContainerBlockEntity rcb && rcb.getLootTable() != null) {
            rcb.unpackLootTable(player);
        }

        if (!(be instanceof Container c)) {
            return;
        }
        int drained = 0;
        Map<String, Integer> found = new LinkedHashMap<>();
        for (int i = 0; i < c.getContainerSize(); i++) {
            ItemStack stack = c.getItem(i);
            if (stack.isEmpty()) continue;
            ItemStack taken = stack.copy();
            c.setItem(i, ItemStack.EMPTY);
            BotPlayer.deliverTo(player, taken);
            int n = taken.getCount();
            drained += n;
            found.merge(stack.getHoverName().getString(), n, Integer::sum);
        }
        if (drained > 0) {
            itemsLooted += drained;
            progress.increment("items_looted", drained);
            // Announce the actual finds the way combat announces hits/kills, so
            // loot is visible in chat instead of being silently paged away.
            String what = summarize(found);
            bot.systemChat("Looted " + what + " from " + p.toShortString(), "green");
            progress.logEvent("Looted " + what + " from " + p.toShortString());
            progress.putResult("last_loot", found);
        }
    }

    /** "3x diamond, 12x iron ingot" — compact so a chest of junk never floods
     *  chat; more than 6 distinct types collapse into "+N more". */
    private static String summarize(Map<String, Integer> found) {
        List<String> parts = new ArrayList<>();
        int shown = 0;
        for (Map.Entry<String, Integer> e : found.entrySet()) {
            if (shown++ >= 6) break;
            parts.add(e.getValue() + "x " + e.getKey());
        }
        String s = String.join(", ", parts);
        int rest = found.size() - shown;
        return rest > 0 ? s + " (+" + rest + " more)" : s;
    }

    private BehaviorResult finish(BotPlayer bot) {
        phase = Phase.DONE;
        String summary = "Looted " + containersLooted + " containers, " + itemsLooted + " items";
        progress.logEvent(summary);
        bot.systemChat(summary, "green");
        return BehaviorResult.SUCCESS;
    }

    private static boolean hasAnyItem(Container c) {
        for (int i = 0; i < c.getContainerSize(); i++) {
            if (!c.getItem(i).isEmpty()) return true;
        }
        return false;
    }

    private static int parseIntOr(String val, int def) {
        if (val == null) return def;
        try {
            return Integer.parseInt(val.trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case SURVEY -> "Area loot — surveying (bot " + (botIndex + 1) + "/" + botCount + ")";
            case LOOTING -> "Area loot — " + index + "/" + targets.size() + " containers";
            case DONE -> "Area loot — done (" + containersLooted + " containers, " + itemsLooted + " items)";
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
