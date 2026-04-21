package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.CraftingContainer;
import net.minecraft.world.inventory.TransientCraftingContainer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.*;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;

import java.util.*;

/**
 * Composite crafting behavior. Handles the full chain:
 * 1. Check if we have materials, or if sub-crafts are needed
 * 2. Find or place a crafting table (for 3x3 recipes)
 * 3. Navigate to it
 * 4. Execute the craft chain
 */
public class CraftBehavior implements Behavior {
    private enum Phase {
        RESOLVING, GATHERING_MATERIALS, FIND_TABLE, PLACE_TABLE, NAVIGATE, CRAFTING, DONE
    }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;
    private String targetItemId;
    private int targetCount;

    private List<CraftStep> craftSteps;
    private int currentCraftStep;
    private BlockPos tablePos;

    // For navigating
    private double yVelocity;
    private int ticksStuck;
    private net.minecraft.world.phys.Vec3 lastPos;

    // For gathering missing materials via mining
    private String gatherTarget;
    private int gatherCount;
    private MineBehavior gatherBehavior;

    private boolean needsTable;

    private static final double REACH = 4.5;
    private static final int TABLE_SEARCH_RADIUS = 16;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.targetItemId = directive.getTarget();
        this.targetCount = directive.getCount() > 0 ? directive.getCount() : 1;
        this.craftSteps = new ArrayList<>();
        this.currentCraftStep = 0;
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        this.gatherBehavior = null;
        this.needsTable = false;
        enterPhase(Phase.RESOLVING);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case RESOLVING -> tickResolving(bot);
            case GATHERING_MATERIALS -> tickGathering(bot);
            case FIND_TABLE -> tickFindTable(bot);
            case PLACE_TABLE -> tickPlaceTable(bot);
            case NAVIGATE -> tickNavigate(bot);
            case CRAFTING -> tickCrafting(bot);
            case DONE -> BehaviorResult.SUCCESS;
        };
    }

    private BehaviorResult tickResolving(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Item target;
        try {
            target = BuiltInRegistries.ITEM.get(ResourceLocation.parse(targetItemId));
        } catch (Exception e) {
            progress.setFailureReason("Invalid item: " + targetItemId);
            return BehaviorResult.FAILED;
        }

        craftSteps.clear();
        if (!resolveChain(target, targetCount, player, new HashSet<>())) {
            progress.setFailureReason("Cannot resolve recipe chain for " + targetItemId);
            return BehaviorResult.FAILED;
        }

        if (craftSteps.isEmpty()) {
            int have = countInInventory(player, target);
            if (have >= targetCount) {
                progress.logEvent("Already have " + have + "x " + targetItemId);
                return BehaviorResult.SUCCESS;
            }
            progress.setFailureReason("No recipe found for " + targetItemId);
            return BehaviorResult.FAILED;
        }

        progress.logEvent("Craft chain: " + craftSteps.size() + " steps");
        currentCraftStep = 0;

        needsTable = checkNeedsTable(player);
        if (needsTable) {
            enterPhase(Phase.FIND_TABLE);
        } else {
            enterPhase(Phase.CRAFTING);
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickGathering(BotPlayer bot) {
        if (gatherBehavior == null) {
            progress.setFailureReason("No gather behavior configured");
            return BehaviorResult.FAILED;
        }
        BehaviorResult result = gatherBehavior.tick(bot);
        if (result == BehaviorResult.SUCCESS) {
            progress.logEvent("Gathered " + gatherTarget);
            gatherBehavior = null;
            enterPhase(Phase.RESOLVING);
        } else if (result == BehaviorResult.FAILED) {
            progress.setFailureReason("Failed to gather " + gatherTarget);
            return BehaviorResult.FAILED;
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickFindTable(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        tablePos = findNearbyBlock(player, Blocks.CRAFTING_TABLE, TABLE_SEARCH_RADIUS);

        if (tablePos != null) {
            progress.logEvent("Found crafting table at " + tablePos.toShortString());
            enterPhase(Phase.NAVIGATE);
            return BehaviorResult.RUNNING;
        }

        // Check if we have a crafting table in inventory
        Item tableItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:crafting_table"));
        int tableCount = countInInventory(player, tableItem);
        if (tableCount > 0) {
            enterPhase(Phase.PLACE_TABLE);
            return BehaviorResult.RUNNING;
        }

        // Need to craft a crafting table (4 planks)
        Item planksItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:oak_planks"));
        int planksNeeded = 4 - countInInventory(player, planksItem);

        if (planksNeeded > 0) {
            // Check for logs to make planks
            Item logItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:oak_log"));
            int logCount = countInInventory(player, logItem);
            // Also check other log types
            for (String logType : new String[]{"birch_log", "spruce_log", "dark_oak_log", "jungle_log", "acacia_log"}) {
                Item lt = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:" + logType));
                logCount += countInInventory(player, lt);
            }

            if (logCount == 0) {
                // Need to gather logs
                progress.logEvent("Need logs for crafting table, mining nearby trees");
                gatherTarget = "log";
                gatherCount = 1;
                gatherBehavior = new MineBehavior();
                Directive gatherDirective = Directive.builder(com.sigmastrain.aiplayermod.brain.DirectiveType.MINE)
                        .target("log").count(1).radius(32).build();
                gatherBehavior.start(bot, gatherDirective);
                enterPhase(Phase.GATHERING_MATERIALS);
                return BehaviorResult.RUNNING;
            }

            // Craft planks from logs
            executeSingleCraft(player, "minecraft:oak_planks", 1);
        }

        // Craft crafting table from planks
        executeSingleCraft(player, "minecraft:crafting_table", 1);

        // Verify we got it
        if (countInInventory(player, tableItem) > 0) {
            enterPhase(Phase.PLACE_TABLE);
        } else {
            progress.setFailureReason("Failed to craft crafting table");
            return BehaviorResult.FAILED;
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickPlaceTable(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        // Place crafting table at feet level, 1 block in front
        BlockPos placePos = player.blockPosition().relative(player.getDirection());
        BlockState existing = player.level().getBlockState(placePos);
        if (!existing.isAir() && !existing.canBeReplaced()) {
            // Try other positions
            for (var dir : net.minecraft.core.Direction.Plane.HORIZONTAL) {
                placePos = player.blockPosition().relative(dir);
                existing = player.level().getBlockState(placePos);
                if (existing.isAir() || existing.canBeReplaced()) break;
            }
        }

        // Remove crafting table from inventory
        Item tableItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:crafting_table"));
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.getItem() == tableItem) {
                stack.shrink(1);
                break;
            }
        }

        player.level().setBlock(placePos, Blocks.CRAFTING_TABLE.defaultBlockState(), 3);
        tablePos = placePos;
        progress.logEvent("Placed crafting table at " + placePos.toShortString());
        enterPhase(Phase.NAVIGATE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickNavigate(BotPlayer bot) {
        if (tablePos == null) {
            enterPhase(Phase.FIND_TABLE);
            return BehaviorResult.RUNNING;
        }

        ServerPlayer player = bot.getPlayer();
        net.minecraft.world.phys.Vec3 target = net.minecraft.world.phys.Vec3.atCenterOf(tablePos);
        double dist = player.position().distanceTo(target);

        if (dist <= REACH) {
            enterPhase(Phase.CRAFTING);
            return BehaviorResult.RUNNING;
        }

        moveToward(bot, player, target, dist);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCrafting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        while (currentCraftStep < craftSteps.size()) {
            CraftStep step = craftSteps.get(currentCraftStep);
            boolean ok = executeSingleCraft(player, step.itemId, step.count);
            if (!ok) {
                progress.setFailureReason("Failed to craft " + step.itemId + " (missing materials)");
                return BehaviorResult.FAILED;
            }
            progress.increment("items_crafted", step.count);
            progress.logEvent("Crafted " + step.count + "x " + step.itemId);
            currentCraftStep++;
        }

        progress.logEvent("Craft chain complete: " + targetItemId);
        return BehaviorResult.SUCCESS;
    }

    private boolean resolveChain(Item target, int needed, ServerPlayer player, Set<String> visited) {
        String targetId = BuiltInRegistries.ITEM.getKey(target).toString();
        if (visited.contains(targetId)) return false;
        visited.add(targetId);

        int have = countInInventory(player, target);
        if (have >= needed) return true;
        int toCraft = needed - have;

        var server = player.getServer();
        var allRecipes = server.getRecipeManager().getAllRecipesFor(RecipeType.CRAFTING);

        RecipeHolder<CraftingRecipe> recipe = null;
        for (var holder : allRecipes) {
            ItemStack result = holder.value().getResultItem(server.registryAccess());
            if (result.getItem() == target) {
                recipe = holder;
                break;
            }
        }
        if (recipe == null) return false;

        ItemStack output = recipe.value().getResultItem(server.registryAccess());
        int batches = (int) Math.ceil((double) toCraft / output.getCount());

        var ingredients = recipe.value().getIngredients();
        for (var ing : ingredients) {
            if (ing.isEmpty()) continue;
            ItemStack[] items = ing.getItems();
            if (items.length == 0) continue;
            Item ingItem = items[0].getItem();
            int ingNeeded = batches;
            if (!resolveChain(ingItem, ingNeeded, player, visited)) {
                return false;
            }
        }

        craftSteps.add(new CraftStep(targetId, batches));
        return true;
    }

    private boolean executeSingleCraft(ServerPlayer player, String itemId, int batches) {
        var server = player.getServer();
        var recipeManager = server.getRecipeManager();
        Item targetItem;
        try {
            targetItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        } catch (Exception e) { return false; }

        var allRecipes = recipeManager.getAllRecipesFor(RecipeType.CRAFTING);
        RecipeHolder<CraftingRecipe> matchedRecipe = null;
        for (var holder : allRecipes) {
            ItemStack result = holder.value().getResultItem(server.registryAccess());
            if (result.getItem() == targetItem) {
                matchedRecipe = holder;
                break;
            }
        }
        if (matchedRecipe == null) return false;

        int crafted = 0;
        for (int batch = 0; batch < batches; batch++) {
            CraftingContainer container = new TransientCraftingContainer(new AbstractContainerMenu(null, -1) {
                @Override public ItemStack quickMoveStack(Player p, int i) { return ItemStack.EMPTY; }
                @Override public boolean stillValid(Player p) { return true; }
            }, 3, 3);

            var ingredients = matchedRecipe.value().getIngredients();
            boolean hasAll = true;
            int[] usedSlots = new int[ingredients.size()];

            for (int i = 0; i < ingredients.size(); i++) {
                Ingredient ing = ingredients.get(i);
                if (ing.isEmpty()) continue;
                boolean found = false;
                for (int s = 0; s < player.getInventory().getContainerSize(); s++) {
                    ItemStack invStack = player.getInventory().getItem(s);
                    if (!invStack.isEmpty() && ing.test(invStack)) {
                        container.setItem(i, invStack.copy().split(1));
                        usedSlots[i] = s;
                        found = true;
                        break;
                    }
                }
                if (!found) { hasAll = false; break; }
            }
            if (!hasAll) return crafted > 0;

            CraftingInput input = container.asCraftInput();
            Optional<RecipeHolder<CraftingRecipe>> match = recipeManager.getRecipeFor(
                    RecipeType.CRAFTING, input, player.level());
            if (match.isEmpty()) return crafted > 0;

            ItemStack result = match.get().value().assemble(input, server.registryAccess());
            if (result.isEmpty()) return crafted > 0;

            for (int i = 0; i < ingredients.size(); i++) {
                if (!ingredients.get(i).isEmpty()) {
                    player.getInventory().getItem(usedSlots[i]).shrink(1);
                }
            }
            player.getInventory().add(result);
            crafted += result.getCount();
        }
        return true;
    }

    private boolean checkNeedsTable(ServerPlayer player) {
        var server = player.getServer();
        for (CraftStep step : craftSteps) {
            Item item;
            try {
                item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(step.itemId));
            } catch (Exception e) { continue; }

            for (var holder : server.getRecipeManager().getAllRecipesFor(RecipeType.CRAFTING)) {
                ItemStack result = holder.value().getResultItem(server.registryAccess());
                if (result.getItem() == item) {
                    var ingredients = holder.value().getIngredients();
                    int nonEmpty = 0;
                    for (var ing : ingredients) {
                        if (!ing.isEmpty()) nonEmpty++;
                    }
                    // 3x3 recipes (more than 4 ingredients) need a crafting table
                    if (nonEmpty > 4) return true;
                    break;
                }
            }
        }
        return false;
    }

    private int countInInventory(ServerPlayer player, Item item) {
        int count = 0;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.getItem() == item) count += stack.getCount();
        }
        return count;
    }

    private BlockPos findNearbyBlock(ServerPlayer player, net.minecraft.world.level.block.Block block, int radius) {
        BlockPos center = player.blockPosition();
        BlockPos nearest = null;
        double nearestDist = Double.MAX_VALUE;
        for (int x = -radius; x <= radius; x++) {
            for (int y = -radius; y <= radius; y++) {
                for (int z = -radius; z <= radius; z++) {
                    BlockPos pos = center.offset(x, y, z);
                    if (player.level().getBlockState(pos).getBlock() == block) {
                        double dist = center.distSqr(pos);
                        if (dist < nearestDist) {
                            nearestDist = dist;
                            nearest = pos;
                        }
                    }
                }
            }
        }
        return nearest;
    }

    private void moveToward(BotPlayer bot, ServerPlayer player, net.minecraft.world.phys.Vec3 target, double dist) {
        net.minecraft.world.phys.Vec3 currentPos = player.position();
        net.minecraft.world.phys.Vec3 direction = target.subtract(currentPos).normalize();

        double heightDiff = Math.abs(target.y - currentPos.y);
        if (heightDiff > 4.0) {
            double moveSpeed = Math.min(0.8, dist);
            player.moveTo(
                    currentPos.x + direction.x * moveSpeed,
                    currentPos.y + direction.y * moveSpeed,
                    currentPos.z + direction.z * moveSpeed
            );
            bot.lookAt(target.x, target.y, target.z);
            return;
        }

        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, direction)) {
                yVelocity = 0.42;
            }
        } else {
            yVelocity -= 0.08;
        }

        if (lastPos != null && currentPos.distanceTo(lastPos) < 0.01) {
            ticksStuck++;
            if (ticksStuck > 20) {
                player.moveTo(currentPos.x + direction.x * 2.0, currentPos.y + 1.0, currentPos.z + direction.z * 2.0);
                yVelocity = 0;
                ticksStuck = 0;
            }
        } else {
            ticksStuck = 0;
        }
        lastPos = currentPos;

        player.move(net.minecraft.world.entity.MoverType.SELF,
                new net.minecraft.world.phys.Vec3(direction.x * 0.4, yVelocity, direction.z * 0.4));
        bot.lookAt(target.x, target.y, target.z);
    }

    private void enterPhase(Phase newPhase) {
        this.phase = newPhase;
        progress.setPhase(newPhase.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case RESOLVING -> "Resolving craft chain for " + targetItemId;
            case GATHERING_MATERIALS -> "Gathering materials for crafting";
            case FIND_TABLE -> "Looking for crafting table";
            case PLACE_TABLE -> "Placing crafting table";
            case NAVIGATE -> "Moving to crafting table";
            case CRAFTING -> "Crafting " + targetItemId;
            case DONE -> "Crafting complete";
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {
        if (gatherBehavior != null) gatherBehavior.stop();
    }

    private record CraftStep(String itemId, int count) {}
}
