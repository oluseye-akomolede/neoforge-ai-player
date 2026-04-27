package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.DirectiveType;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.CraftingContainer;
import net.minecraft.world.inventory.TransientCraftingContainer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.crafting.*;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.Vec3;

import java.util.*;

/**
 * L1 Craft behavior with self-healing fallbacks:
 * 1. Resolve recipe chain
 * 2. If materials missing → channel them (XP cost)
 * 3. If crafting table needed → search escalating radius → channel one
 * 4. Navigate → craft
 */
public class CraftBehavior implements Behavior {
    private enum Phase {
        RESOLVING, CHANNEL_MATERIALS, FIND_TABLE, PLACE_TABLE, NAVIGATE, CRAFTING, CHANNEL_TABLE
    }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;
    private String targetItemId;
    private int targetCount;

    private List<CraftStep> craftSteps;
    private int currentCraftStep;
    private BlockPos tablePos;
    private boolean needsTable;

    // Channeling state
    private List<ChannelRequest> channelQueue;
    private int channelIndex;
    private int channelTicks;
    private int channelXpCost;

    // Table search escalation
    private static final int[] TABLE_SEARCH_RADII = {32, 64, 128, 256};
    private int tableRadiusIndex;

    // Navigation
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;

    private static final double REACH = 4.5;
    private static final int TICKS_PER_LEVEL = 5;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.targetItemId = directive.getTarget();
        this.targetCount = directive.getCount() > 0 ? directive.getCount() : 1;
        this.craftSteps = new ArrayList<>();
        this.currentCraftStep = 0;
        this.channelQueue = new ArrayList<>();
        this.channelIndex = 0;
        this.tableRadiusIndex = 0;
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        this.needsTable = false;
        enterPhase(Phase.RESOLVING);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case RESOLVING -> tickResolving(bot);
            case CHANNEL_MATERIALS -> tickChanneling(bot);
            case FIND_TABLE -> tickFindTable(bot);
            case CHANNEL_TABLE -> tickChannelTable(bot);
            case PLACE_TABLE -> tickPlaceTable(bot);
            case NAVIGATE -> tickNavigate(bot);
            case CRAFTING -> tickCrafting(bot);
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

        // Already have enough?
        if (countInInventory(player, target) >= targetCount) {
            progress.logEvent("Already have " + targetCount + "x " + targetItemId);
            return BehaviorResult.SUCCESS;
        }

        craftSteps.clear();
        channelQueue.clear();
        Set<String> visited = new HashSet<>();

        resolveChain(target, targetCount, player, visited);

        // Log the full resolution
        if (!channelQueue.isEmpty()) {
            AIPlayerMod.LOGGER.info("CraftBehavior: {} requires channeling {} items: {}", targetItemId,
                channelQueue.size(),
                channelQueue.stream().map(c -> c.itemId + "x" + c.count).collect(java.util.stream.Collectors.joining(", ")));
        }
        if (!craftSteps.isEmpty()) {
            AIPlayerMod.LOGGER.info("CraftBehavior: {} craft queue ({} steps): {}", targetItemId,
                craftSteps.size(),
                craftSteps.stream().map(s -> s.itemId + "x" + s.count).collect(java.util.stream.Collectors.joining(" → ")));
        }

        if (craftSteps.isEmpty() && channelQueue.isEmpty()) {
            progress.setFailureReason("No recipe found for " + targetItemId);
            return BehaviorResult.FAILED;
        }

        // Channel first, then craft
        if (!channelQueue.isEmpty()) {
            channelIndex = 0;
            startNextChannel(player);
            enterPhase(Phase.CHANNEL_MATERIALS);
            return BehaviorResult.RUNNING;
        }

        progress.logEvent("Craft chain: " + craftSteps.size() + " steps");
        currentCraftStep = 0;
        needsTable = checkNeedsTable(player);
        if (needsTable) {
            tableRadiusIndex = 0;
            enterPhase(Phase.FIND_TABLE);
        } else {
            enterPhase(Phase.CRAFTING);
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickChanneling(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();

        if (channelTicks % 3 == 0) {
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 1.0, pos.z, 2, 0.8, 0.5, 0.8, 0.2);
        }

        channelTicks--;
        if (channelTicks > 0) return BehaviorResult.RUNNING;

        // Complete this channel
        ChannelRequest req = channelQueue.get(channelIndex);
        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(req.itemId));
        if (item == Items.AIR) {
            progress.setFailureReason("Channel failed: unknown item " + req.itemId);
            return BehaviorResult.FAILED;
        }

        player.giveExperienceLevels(-channelXpCost);
        player.getInventory().add(new ItemStack(item, req.count));
        progress.increment("items_channeled", req.count);
        progress.logEvent("Channeled " + req.count + "x " + req.itemId);

        level.sendParticles(ParticleTypes.END_ROD,
                pos.x, pos.y + 1.0, pos.z, 10, 0.5, 0.8, 0.5, 0.1);
        level.playSound(null, player.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.5f, 1.2f);

        channelIndex++;
        if (channelIndex < channelQueue.size()) {
            startNextChannel(player);
            return BehaviorResult.RUNNING;
        }

        // All materials channeled — proceed to crafting
        bot.systemChat("Materials channeled, crafting " + targetItemId, "light_purple");
        if (craftSteps.isEmpty() || currentCraftStep >= craftSteps.size()) {
            // No craft steps queued — re-resolve (shouldn't happen normally)
            enterPhase(Phase.RESOLVING);
        } else {
            needsTable = checkNeedsTable(player);
            if (needsTable && tablePos == null) {
                tableRadiusIndex = 0;
                enterPhase(Phase.FIND_TABLE);
            } else {
                enterPhase(Phase.CRAFTING);
            }
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickFindTable(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        int radius = TABLE_SEARCH_RADII[Math.min(tableRadiusIndex, TABLE_SEARCH_RADII.length - 1)];
        tablePos = findNearbyBlock(player, Blocks.CRAFTING_TABLE, radius);

        if (tablePos != null) {
            progress.logEvent("Found crafting table at " + tablePos.toShortString());
            enterPhase(Phase.NAVIGATE);
            return BehaviorResult.RUNNING;
        }

        // Check inventory for a crafting table
        Item tableItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:crafting_table"));
        if (countInInventory(player, tableItem) > 0) {
            enterPhase(Phase.PLACE_TABLE);
            return BehaviorResult.RUNNING;
        }

        tableRadiusIndex++;
        if (tableRadiusIndex < TABLE_SEARCH_RADII.length) {
            progress.logEvent("Expanding table search to " + TABLE_SEARCH_RADII[tableRadiusIndex] + " blocks");
            return BehaviorResult.RUNNING;
        }

        // Exhausted search — channel a crafting table
        progress.logEvent("No crafting table found, channeling one");
        bot.systemChat("Channeling crafting table", "light_purple");
        channelXpCost = 2; // Crafting table is cheap
        if (player.experienceLevel < channelXpCost) {
            player.giveExperienceLevels(channelXpCost - player.experienceLevel);
        }
        channelTicks = channelXpCost * TICKS_PER_LEVEL;
        enterPhase(Phase.CHANNEL_TABLE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickChannelTable(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();

        if (channelTicks % 3 == 0) {
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 1.0, pos.z, 2, 0.6, 0.4, 0.6, 0.15);
        }

        channelTicks--;
        if (channelTicks > 0) return BehaviorResult.RUNNING;

        // Give crafting table
        player.giveExperienceLevels(-channelXpCost);
        Item tableItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse("minecraft:crafting_table"));
        player.getInventory().add(new ItemStack(tableItem, 1));
        progress.logEvent("Channeled crafting table");

        level.sendParticles(ParticleTypes.END_ROD,
                pos.x, pos.y + 1.0, pos.z, 10, 0.5, 0.8, 0.5, 0.1);
        level.playSound(null, player.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.5f, 1.2f);

        enterPhase(Phase.PLACE_TABLE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickPlaceTable(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        BlockPos placePos = player.blockPosition().relative(player.getDirection());
        BlockState existing = player.level().getBlockState(placePos);
        if (!existing.isAir() && !existing.canBeReplaced()) {
            for (var dir : net.minecraft.core.Direction.Plane.HORIZONTAL) {
                placePos = player.blockPosition().relative(dir);
                existing = player.level().getBlockState(placePos);
                if (existing.isAir() || existing.canBeReplaced()) break;
            }
        }

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
        Vec3 target = Vec3.atCenterOf(tablePos);
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

        if (currentCraftStep >= craftSteps.size()) {
            progress.logEvent("Craft chain complete: " + targetItemId);
            return BehaviorResult.SUCCESS;
        }

        // Process one step per tick to avoid server lag
        CraftStep step = craftSteps.get(currentCraftStep);
        boolean ok = executeSingleCraft(player, step.itemId, step.count);
        if (!ok) {
            progress.logEvent("Craft step failed for " + step.itemId + ", channeling missing materials");
            // Channel the item directly as fallback
            channelQueue = new ArrayList<>();
            channelQueue.add(new ChannelRequest(step.itemId, step.count));
            channelIndex = 0;
            startNextChannel(player);
            currentCraftStep++;
            enterPhase(Phase.CHANNEL_MATERIALS);
            return BehaviorResult.RUNNING;
        }

        progress.increment("items_crafted", step.count);
        progress.logEvent("Crafted " + step.count + "x " + step.itemId);
        currentCraftStep++;
        return BehaviorResult.RUNNING;
    }

    // ── Recipe Resolution ──

    private RecipeHolder<CraftingRecipe> findVanillaRecipe(Item target, ServerPlayer player) {
        var server = player.getServer();
        var allRecipes = server.getRecipeManager().getAllRecipesFor(RecipeType.CRAFTING);
        RecipeHolder<CraftingRecipe> fallback = null;
        String targetId = BuiltInRegistries.ITEM.getKey(target).toString();
        for (var holder : allRecipes) {
            ItemStack result = holder.value().getResultItem(server.registryAccess());
            if (result.getItem() != target) continue;

            // Skip nugget/block conversion recipes to avoid circular chains
            // (e.g. iron_ingot <-> iron_nugget, iron_ingot <-> iron_block)
            if (isCircularConversion(holder, targetId)) continue;

            if (holder.id().getNamespace().equals("minecraft")) {
                return holder;
            }
            if (fallback == null) {
                boolean allVanillaIngredients = true;
                for (var ing : holder.value().getIngredients()) {
                    if (ing.isEmpty()) continue;
                    for (ItemStack stack : ing.getItems()) {
                        if (!BuiltInRegistries.ITEM.getKey(stack.getItem()).getNamespace().equals("minecraft")) {
                            allVanillaIngredients = false;
                            break;
                        }
                    }
                    if (!allVanillaIngredients) break;
                }
                if (allVanillaIngredients) fallback = holder;
            }
        }
        return fallback;
    }

    private boolean isCircularConversion(RecipeHolder<CraftingRecipe> holder, String targetId) {
        String path = holder.id().getPath();
        if (path.contains("nugget")
                || (path.contains("_from_") && path.contains("block"))
                || path.contains("_from_ingots")) {
            return true;
        }
        // Detect storage block packing (9x same item → 1 block) e.g. iron_ingot → iron_block
        List<Ingredient> ingredients = holder.value().getIngredients();
        if (ingredients.size() == 9) {
            Set<Item> unique = new HashSet<>();
            for (Ingredient ing : ingredients) {
                if (ing.isEmpty()) return false;
                ItemStack[] items = ing.getItems();
                if (items.length == 0) return false;
                unique.add(items[0].getItem());
            }
            if (unique.size() == 1 && path.endsWith("_block")) return true;
        }
        return false;
    }

    private boolean resolveChain(Item target, int needed, ServerPlayer player, Set<String> visited) {
        String targetId = BuiltInRegistries.ITEM.getKey(target).toString();
        if (visited.contains(targetId)) {
            // Cycle — channel this item
            channelQueue.add(new ChannelRequest(targetId, needed));
            return true;
        }
        visited.add(targetId);

        int have = countInInventory(player, target);
        if (have >= needed) return true;
        int toCraft = needed - have;

        RecipeHolder<CraftingRecipe> recipe = findVanillaRecipe(target, player);
        if (recipe == null) {
            // No craftable recipe — channel this item
            channelQueue.add(new ChannelRequest(targetId, toCraft));
            return true;
        }

        ItemStack output = recipe.value().getResultItem(player.getServer().registryAccess());
        int batches = (int) Math.ceil((double) toCraft / output.getCount());

        // Aggregate ingredient counts (same item may appear in multiple slots)
        Map<Item, Integer> ingCounts = new LinkedHashMap<>();
        for (var ing : recipe.value().getIngredients()) {
            if (ing.isEmpty()) continue;
            ItemStack[] items = ing.getItems();
            if (items.length == 0) continue;
            ingCounts.merge(items[0].getItem(), batches, Integer::sum);
        }
        for (var entry : ingCounts.entrySet()) {
            resolveChain(entry.getKey(), entry.getValue(), player, visited);
        }

        craftSteps.add(new CraftStep(targetId, batches));
        return true;
    }

    /**
     * When resolveChain fails, identify what raw materials are missing
     * and build a channel request list.
     */
    private List<ChannelRequest> findMissingMaterials(Item target, int needed, ServerPlayer player) {
        List<ChannelRequest> missing = new ArrayList<>();
        findMissingRecursive(target, needed, player, new HashSet<>(), missing);
        return missing;
    }

    private void findMissingRecursive(Item target, int needed, ServerPlayer player,
                                       Set<String> visited, List<ChannelRequest> missing) {
        String targetId = BuiltInRegistries.ITEM.getKey(target).toString();
        if (visited.contains(targetId)) return;
        visited.add(targetId);

        int have = countInInventory(player, target);
        if (have >= needed) return;
        int shortfall = needed - have;

        RecipeHolder<CraftingRecipe> recipe = findVanillaRecipe(target, player);

        if (recipe == null) {
            missing.add(new ChannelRequest(targetId, shortfall));
            return;
        }

        ItemStack output = recipe.value().getResultItem(player.getServer().registryAccess());
        int batches = (int) Math.ceil((double) shortfall / output.getCount());

        // Aggregate ingredient counts (same item may appear in multiple slots)
        Map<Item, Integer> ingCounts = new LinkedHashMap<>();
        for (var ing : recipe.value().getIngredients()) {
            if (ing.isEmpty()) continue;
            ItemStack[] items = ing.getItems();
            if (items.length == 0) continue;
            ingCounts.merge(items[0].getItem(), batches, Integer::sum);
        }
        for (var entry : ingCounts.entrySet()) {
            findMissingRecursive(entry.getKey(), entry.getValue(), player, visited, missing);
        }
    }

    private List<ChannelRequest> findMissingForStep(CraftStep step, ServerPlayer player) {
        Item item;
        try {
            item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(step.itemId));
        } catch (Exception e) { return List.of(); }

        return findMissingMaterials(item, step.count, player);
    }

    private void startNextChannel(ServerPlayer player) {
        ChannelRequest req = channelQueue.get(channelIndex);
        channelXpCost = getConjureCost(req.itemId) * req.count;
        if (player.experienceLevel < channelXpCost) {
            int needed = channelXpCost - player.experienceLevel;
            player.giveExperienceLevels(needed);
            progress.logEvent("Meditated for " + needed + " XP levels");
        }
        channelTicks = Math.max(5, channelXpCost * TICKS_PER_LEVEL);
        progress.logEvent("Channeling " + req.count + "x " + req.itemId + " (" + channelXpCost + " levels)");
    }

    // ── Crafting Execution ──

    private boolean executeSingleCraft(ServerPlayer player, String itemId, int batches) {
        Item targetItem;
        try {
            targetItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        } catch (Exception e) { return false; }

        RecipeHolder<CraftingRecipe> matchedRecipe = findVanillaRecipe(targetItem, player);
        if (matchedRecipe == null) {
            AIPlayerMod.LOGGER.info("CraftBehavior: executeSingleCraft no recipe for {}", itemId);
            return false;
        }

        int recipeWidth = 3;
        if (matchedRecipe.value() instanceof ShapedRecipe shaped) {
            recipeWidth = shaped.getWidth();
        }

        int crafted = 0;
        for (int batch = 0; batch < batches; batch++) {
            CraftingContainer container = new TransientCraftingContainer(new AbstractContainerMenu(null, -1) {
                @Override public ItemStack quickMoveStack(Player p, int i) { return ItemStack.EMPTY; }
                @Override public boolean stillValid(Player p) { return true; }
            }, 3, 3);

            var ingredients = matchedRecipe.value().getIngredients();
            boolean hasAll = true;
            Map<Integer, Integer> slotUsage = new HashMap<>();

            for (int i = 0; i < ingredients.size(); i++) {
                Ingredient ing = ingredients.get(i);
                if (ing.isEmpty()) continue;

                int gridIdx = i;
                if (matchedRecipe.value() instanceof ShapedRecipe && recipeWidth < 3) {
                    int row = i / recipeWidth;
                    int col = i % recipeWidth;
                    gridIdx = row * 3 + col;
                }

                boolean found = false;
                for (int s = 0; s < player.getInventory().getContainerSize(); s++) {
                    ItemStack invStack = player.getInventory().getItem(s);
                    if (invStack.isEmpty() || !ing.test(invStack)) continue;
                    int used = slotUsage.getOrDefault(s, 0);
                    if (invStack.getCount() > used) {
                        container.setItem(gridIdx, invStack.copy().split(1));
                        slotUsage.merge(s, 1, Integer::sum);
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    AIPlayerMod.LOGGER.info("CraftBehavior: executeSingleCraft {} batch {} missing ingredient idx {} (grid {})",
                        itemId, batch, i, gridIdx);
                    hasAll = false;
                    break;
                }
            }
            if (!hasAll) return crafted > 0;

            CraftingInput input = container.asCraftInput();
            Optional<RecipeHolder<CraftingRecipe>> match = player.getServer().getRecipeManager().getRecipeFor(
                    RecipeType.CRAFTING, input, player.level());
            if (match.isEmpty()) {
                AIPlayerMod.LOGGER.info("CraftBehavior: executeSingleCraft {} batch {} recipe match failed (width={})",
                    itemId, batch, recipeWidth);
                return crafted > 0;
            }

            ItemStack result = match.get().value().assemble(input, player.getServer().registryAccess());
            if (result.isEmpty()) return crafted > 0;

            for (var entry : slotUsage.entrySet()) {
                player.getInventory().getItem(entry.getKey()).shrink(entry.getValue());
            }
            player.getInventory().add(result);
            crafted += result.getCount();
        }
        return true;
    }

    // ── Helpers ──

    private boolean checkNeedsTable(ServerPlayer player) {
        for (CraftStep step : craftSteps) {
            Item item;
            try {
                item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(step.itemId));
            } catch (Exception e) { continue; }

            var holder = findVanillaRecipe(item, player);
            if (holder != null) {
                var ingredients = holder.value().getIngredients();
                int nonEmpty = 0;
                for (var ing : ingredients) {
                    if (!ing.isEmpty()) nonEmpty++;
                }
                if (nonEmpty > 4) return true;
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

    private void moveToward(BotPlayer bot, ServerPlayer player, Vec3 target, double dist) {
        Vec3 currentPos = player.position();
        Vec3 direction = target.subtract(currentPos).normalize();

        if (Math.abs(target.y - currentPos.y) > 4.0) {
            double moveSpeed = Math.min(0.8, dist);
            player.moveTo(
                    currentPos.x + direction.x * moveSpeed,
                    currentPos.y + direction.y * moveSpeed,
                    currentPos.z + direction.z * moveSpeed);
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
                new Vec3(direction.x * 0.4, yVelocity, direction.z * 0.4));
        bot.lookAt(target.x, target.y, target.z);
    }

    private int getConjureCost(String itemId) {
        return switch (itemId) {
            case "minecraft:dirt", "minecraft:cobblestone", "minecraft:sand",
                 "minecraft:gravel", "minecraft:clay_ball", "minecraft:stick",
                 "minecraft:oak_log", "minecraft:spruce_log", "minecraft:birch_log",
                 "minecraft:jungle_log", "minecraft:acacia_log", "minecraft:dark_oak_log",
                 "minecraft:oak_planks", "minecraft:spruce_planks", "minecraft:birch_planks" -> 1;
            case "minecraft:coal", "minecraft:charcoal", "minecraft:raw_copper" -> 2;
            case "minecraft:raw_iron", "minecraft:iron_ingot", "minecraft:raw_gold",
                 "minecraft:gold_ingot", "minecraft:lapis_lazuli", "minecraft:redstone",
                 "minecraft:quartz" -> 3;
            case "minecraft:emerald", "minecraft:blaze_rod", "minecraft:ender_pearl" -> 5;
            case "minecraft:diamond" -> 15;
            case "minecraft:obsidian" -> 4;
            default -> 8;
        };
    }

    private void enterPhase(Phase newPhase) {
        this.phase = newPhase;
        progress.setPhase(newPhase.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case RESOLVING -> "Resolving craft chain for " + targetItemId;
            case CHANNEL_MATERIALS -> "Channeling materials for " + targetItemId;
            case FIND_TABLE -> "Searching for crafting table";
            case CHANNEL_TABLE -> "Channeling crafting table";
            case PLACE_TABLE -> "Placing crafting table";
            case NAVIGATE -> "Moving to crafting table";
            case CRAFTING -> "Crafting " + targetItemId;
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}

    private record CraftStep(String itemId, int count) {}
    private record ChannelRequest(String itemId, int count) {}
}
