package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.*;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.Vec3;

import java.util.*;

/**
 * Searches random containers from the registry.
 * Checks if each still exists, removes destroyed ones, reports/collects target items.
 * Directive target = item to search for (optional; if null, just audits).
 * Directive count = max containers to check (default 5).
 */
public class ContainerSearchBehavior implements Behavior {
    private enum Phase { SELECTING, PATHING, INSPECTING, DONE }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String searchItemId;
    private Item searchItem;
    private int maxCheck;
    private List<ContainerRegistry.ContainerEntry> toCheck;
    private int checkIndex;
    private int containersChecked;
    private int containersRemoved;
    private int itemsFound;
    private int itemsCollected;

    private static final double REACH = 4.5;
    private static final double MOVE_SPEED = 0.4;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();

        searchItemId = directive.getTarget();
        if (searchItemId != null && !searchItemId.isEmpty()) {
            if (!searchItemId.contains(":")) searchItemId = "minecraft:" + searchItemId;
            searchItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(searchItemId));
            if (searchItem == Items.AIR) searchItem = null;
        }

        maxCheck = directive.getCount() > 0 ? directive.getCount() : 5;

        ServerPlayer player = bot.getPlayer();
        String dimension = player.serverLevel().dimension().location().toString();
        toCheck = ContainerRegistry.get().getRandom(dimension, maxCheck);

        if (toCheck.isEmpty()) {
            progress.setFailureReason("No containers registered in " + dimension);
            return;
        }

        checkIndex = 0;
        containersChecked = 0;
        containersRemoved = 0;
        itemsFound = 0;
        itemsCollected = 0;
        phase = Phase.PATHING;

        String searchDesc = searchItemId != null ? " for " + searchItemId : "";
        progress.logEvent("Searching " + toCheck.size() + " containers" + searchDesc);
        bot.systemChat("Searching " + toCheck.size() + " containers" + searchDesc, "aqua");
        AIPlayerMod.LOGGER.info("[{}] CONTAINER_SEARCH: {} containers{}",
                player.getName().getString(), toCheck.size(), searchDesc);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (progress.toMap().containsKey("failure_reason")) return BehaviorResult.FAILED;

        return switch (phase) {
            case SELECTING -> BehaviorResult.FAILED;
            case PATHING -> tickPathing(bot);
            case INSPECTING -> tickInspecting(bot);
            case DONE -> BehaviorResult.SUCCESS;
        };
    }

    private BehaviorResult tickPathing(BotPlayer bot) {
        if (checkIndex >= toCheck.size()) {
            return finishSearch(bot);
        }

        ServerPlayer player = bot.getPlayer();
        ContainerRegistry.ContainerEntry entry = toCheck.get(checkIndex);
        BlockPos target = entry.pos();
        Vec3 targetVec = Vec3.atCenterOf(target);
        double dist = player.position().distanceTo(targetVec);

        progress.setPhase("pathing to #" + entry.id() + " (" + (checkIndex + 1) + "/" + toCheck.size() + ")");

        if (dist <= REACH) {
            phase = Phase.INSPECTING;
            return BehaviorResult.RUNNING;
        }

        // Teleport to container (search is a utility operation, not immersive travel)
        if (dist > REACH) {
            player.moveTo(targetVec.x, targetVec.y, targetVec.z);
            phase = Phase.INSPECTING;
            return BehaviorResult.RUNNING;
        }

        Vec3 dir = targetVec.subtract(player.position()).normalize();
        player.move(MoverType.SELF, new Vec3(dir.x * MOVE_SPEED, 0, dir.z * MOVE_SPEED));
        bot.lookAt(targetVec.x, targetVec.y, targetVec.z);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickInspecting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        ContainerRegistry.ContainerEntry entry = toCheck.get(checkIndex);
        BlockPos pos = entry.pos();

        containersChecked++;
        progress.setPhase("inspecting #" + entry.id());

        BlockState state = level.getBlockState(pos);
        BlockEntity be = level.getBlockEntity(pos);

        if (!(be instanceof Container container)) {
            // Container is gone — remove from registry
            ContainerRegistry.get().remove(entry.id());
            containersRemoved++;
            progress.increment("containers_removed");
            progress.logEvent("Container #" + entry.id() + " destroyed at " + pos.toShortString());
            bot.systemChat("Container #" + entry.id() + " missing — removed", "red");
        } else {
            // Scan contents
            int foundHere = 0;
            for (int i = 0; i < container.getContainerSize(); i++) {
                ItemStack stack = container.getItem(i);
                if (stack.isEmpty()) continue;

                if (searchItem != null && stack.is(searchItem)) {
                    foundHere += stack.getCount();
                    // Collect the items
                    ItemStack taken = stack.copy();
                    container.setItem(i, ItemStack.EMPTY);
                    player.getInventory().add(taken);
                    itemsCollected += taken.getCount();
                }
            }

            if (foundHere > 0) {
                itemsFound += foundHere;
                progress.increment("items_found", foundHere);
                bot.systemChat("Found " + foundHere + "x " + searchItemId + " in #" + entry.id(), "green");
            }
            progress.increment("containers_checked");
        }

        checkIndex++;
        if (checkIndex >= toCheck.size()) {
            return finishSearch(bot);
        }
        phase = Phase.PATHING;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult finishSearch(BotPlayer bot) {
        phase = Phase.DONE;
        String summary = "Searched " + containersChecked + " containers";
        if (containersRemoved > 0) summary += ", removed " + containersRemoved + " destroyed";
        if (itemsFound > 0) summary += ", collected " + itemsCollected + "x " + searchItemId;
        progress.logEvent(summary);
        bot.systemChat(summary, "green");
        return BehaviorResult.SUCCESS;
    }

    @Override
    public String describeState() {
        return "Searching containers (" + containersChecked + "/" + toCheck.size() + ")";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
