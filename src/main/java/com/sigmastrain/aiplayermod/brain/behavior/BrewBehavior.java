package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.entity.BrewingStandBlockEntity;
import net.minecraft.world.phys.Vec3;

import java.util.*;

/**
 * Composite brewing behavior. Handles:
 * 1. Find brewing stand (won't auto-craft — needs blaze rods)
 * 2. Navigate to it
 * 3. Resolve the brewing recipe chain (water bottle → awkward → effect → modifier)
 * 4. Execute each brewing stage: load, wait, collect
 * 5. Repeat for multi-stage recipes
 */
public class BrewBehavior implements Behavior {
    private enum Phase {
        RESOLVE, FIND_STAND, NAVIGATE, CHECK_FUEL, LOAD_STAGE, WAITING, COLLECT_STAGE
    }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String targetPotion;
    private int targetCount;
    private BlockPos standPos;

    private List<BrewStage> stages;
    private int currentStage;
    private int waitTicks;

    // Navigation
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;

    private static final double REACH = 4.5;
    private static final int STAND_SEARCH_RADIUS = 24;
    private static final int MAX_WAIT_TICKS = 500;

    // ── Potion recipe table ──
    // Maps potion effect name → list of brewing stages (ingredient item IDs in order)
    // Stage 0 always uses nether_wart on water bottles to make awkward potion
    private static final Map<String, List<String>> POTION_RECIPES = new LinkedHashMap<>();
    // Modifier potions (applied to existing effect potions)
    private static final Map<String, String> MODIFIERS = new LinkedHashMap<>();

    static {
        // Base potions: nether_wart → awkward, then ingredient → effect
        POTION_RECIPES.put("healing",        List.of("minecraft:nether_wart", "minecraft:glistering_melon_slice"));
        POTION_RECIPES.put("regeneration",   List.of("minecraft:nether_wart", "minecraft:ghast_tear"));
        POTION_RECIPES.put("strength",       List.of("minecraft:nether_wart", "minecraft:blaze_powder"));
        POTION_RECIPES.put("swiftness",      List.of("minecraft:nether_wart", "minecraft:sugar"));
        POTION_RECIPES.put("night_vision",   List.of("minecraft:nether_wart", "minecraft:golden_carrot"));
        POTION_RECIPES.put("invisibility",   List.of("minecraft:nether_wart", "minecraft:golden_carrot", "minecraft:fermented_spider_eye"));
        POTION_RECIPES.put("fire_resistance",List.of("minecraft:nether_wart", "minecraft:magma_cream"));
        POTION_RECIPES.put("water_breathing",List.of("minecraft:nether_wart", "minecraft:pufferfish"));
        POTION_RECIPES.put("leaping",        List.of("minecraft:nether_wart", "minecraft:rabbit_foot"));
        POTION_RECIPES.put("slow_falling",   List.of("minecraft:nether_wart", "minecraft:phantom_membrane"));
        POTION_RECIPES.put("poison",         List.of("minecraft:nether_wart", "minecraft:spider_eye"));
        POTION_RECIPES.put("weakness",       List.of("minecraft:fermented_spider_eye")); // No awkward base needed
        POTION_RECIPES.put("slowness",       List.of("minecraft:nether_wart", "minecraft:sugar", "minecraft:fermented_spider_eye"));
        POTION_RECIPES.put("harming",        List.of("minecraft:nether_wart", "minecraft:glistering_melon_slice", "minecraft:fermented_spider_eye"));
        POTION_RECIPES.put("turtle_master",  List.of("minecraft:nether_wart", "minecraft:turtle_helmet"));

        // Modifiers: applied as an extra stage on top of any effect potion
        MODIFIERS.put("long",     "minecraft:redstone");      // Extended duration
        MODIFIERS.put("strong",   "minecraft:glowstone_dust"); // Increased potency
        MODIFIERS.put("splash",   "minecraft:gunpowder");     // Splash variant
        MODIFIERS.put("lingering","minecraft:dragon_breath");  // Lingering variant
    }

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.targetPotion = directive.getTarget();
        this.targetCount = directive.getCount() > 0 ? Math.min(directive.getCount(), 3) : 3;
        this.stages = new ArrayList<>();
        this.currentStage = 0;
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        enterPhase(Phase.RESOLVE);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case RESOLVE -> tickResolve(bot);
            case FIND_STAND -> tickFindStand(bot);
            case NAVIGATE -> tickNavigate(bot);
            case CHECK_FUEL -> tickCheckFuel(bot);
            case LOAD_STAGE -> tickLoadStage(bot);
            case WAITING -> tickWaiting(bot);
            case COLLECT_STAGE -> tickCollectStage(bot);
        };
    }

    private BehaviorResult tickResolve(BotPlayer bot) {
        // Parse potion name: "healing", "long_strength", "splash_healing", "strong_regeneration"
        String potionName = targetPotion.toLowerCase()
                .replace("minecraft:", "")
                .replace("potion_of_", "")
                .replace("potion of ", "")
                .replace("_potion", "")
                .replace(" potion", "")
                .trim();

        // Check for modifiers
        String modifier = null;
        for (String mod : MODIFIERS.keySet()) {
            if (potionName.startsWith(mod + "_")) {
                modifier = mod;
                potionName = potionName.substring(mod.length() + 1);
                break;
            }
        }

        List<String> recipe = POTION_RECIPES.get(potionName);
        if (recipe == null) {
            // Try fuzzy match
            for (var entry : POTION_RECIPES.entrySet()) {
                if (potionName.contains(entry.getKey()) || entry.getKey().contains(potionName)) {
                    recipe = entry.getValue();
                    potionName = entry.getKey();
                    break;
                }
            }
        }

        if (recipe == null) {
            progress.setFailureReason("Unknown potion: " + targetPotion + ". Known: " + String.join(", ", POTION_RECIPES.keySet()));
            return BehaviorResult.FAILED;
        }

        stages.clear();
        for (String ingredientId : recipe) {
            stages.add(new BrewStage(ingredientId));
        }
        if (modifier != null && MODIFIERS.containsKey(modifier)) {
            stages.add(new BrewStage(MODIFIERS.get(modifier)));
        }

        progress.logEvent("Brewing " + potionName + ": " + stages.size() + " stage(s)"
                + (modifier != null ? " + " + modifier : ""));
        currentStage = 0;

        // Check we have all ingredients
        ServerPlayer player = bot.getPlayer();
        for (BrewStage stage : stages) {
            if (findItemSlot(player, stage.ingredientId) < 0) {
                progress.setFailureReason("Missing ingredient: " + stage.ingredientId);
                return BehaviorResult.FAILED;
            }
        }

        // Check for water bottles (need targetCount)
        int bottleCount = countBottles(player);
        if (bottleCount < targetCount) {
            progress.setFailureReason("Need " + targetCount + " water bottles but only have " + bottleCount);
            return BehaviorResult.FAILED;
        }

        enterPhase(Phase.FIND_STAND);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickFindStand(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        standPos = findNearbyBlock(player, "brewing_stand", STAND_SEARCH_RADIUS);
        if (standPos == null) {
            progress.setFailureReason("No brewing stand within " + STAND_SEARCH_RADIUS + " blocks");
            return BehaviorResult.FAILED;
        }
        progress.logEvent("Found brewing stand at " + standPos.toShortString());
        enterPhase(Phase.NAVIGATE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickNavigate(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Vec3 target = Vec3.atCenterOf(standPos);
        double dist = player.position().distanceTo(target);

        if (dist <= REACH) {
            enterPhase(Phase.CHECK_FUEL);
            return BehaviorResult.RUNNING;
        }

        moveToward(bot, player, target, dist);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCheckFuel(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (!(player.level().getBlockEntity(standPos) instanceof BrewingStandBlockEntity stand)) {
            progress.setFailureReason("Brewing stand block entity missing");
            return BehaviorResult.FAILED;
        }

        // Check if stand needs fuel (blaze powder, slot 4)
        ItemStack existingFuel = stand.getItem(4);
        if (existingFuel.isEmpty()) {
            int blazeSlot = findItemSlot(player, "minecraft:blaze_powder");
            if (blazeSlot >= 0) {
                ItemStack fuel = player.getInventory().getItem(blazeSlot);
                stand.setItem(4, fuel.split(1));
                stand.setChanged();
                progress.logEvent("Loaded blaze powder as fuel");
            } else {
                progress.setFailureReason("Brewing stand needs blaze powder fuel but none in inventory");
                return BehaviorResult.FAILED;
            }
        }

        enterPhase(Phase.LOAD_STAGE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickLoadStage(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (currentStage >= stages.size()) {
            progress.logEvent("All brewing stages complete");
            return BehaviorResult.SUCCESS;
        }

        if (!(player.level().getBlockEntity(standPos) instanceof BrewingStandBlockEntity stand)) {
            progress.setFailureReason("Brewing stand disappeared");
            return BehaviorResult.FAILED;
        }

        BrewStage stage = stages.get(currentStage);

        // Load bottles into slots 0-2
        if (currentStage == 0) {
            // First stage: load water bottles from inventory
            int loaded = 0;
            for (int slot = 0; slot < 3 && loaded < targetCount; slot++) {
                int bottleIdx = findWaterBottleSlot(player);
                if (bottleIdx >= 0) {
                    ItemStack bottle = player.getInventory().getItem(bottleIdx);
                    stand.setItem(slot, bottle.split(1));
                    loaded++;
                }
            }
            if (loaded == 0) {
                progress.setFailureReason("No water bottles to load");
                return BehaviorResult.FAILED;
            }
            progress.logEvent("Loaded " + loaded + " water bottle(s)");
        }
        // Subsequent stages: bottles are already in the stand from previous collection/reload

        // Load ingredient into slot 3
        int ingredientSlot = findItemSlot(player, stage.ingredientId);
        if (ingredientSlot < 0) {
            progress.setFailureReason("Missing ingredient: " + stage.ingredientId);
            return BehaviorResult.FAILED;
        }
        ItemStack ingredient = player.getInventory().getItem(ingredientSlot);
        stand.setItem(3, ingredient.split(1));
        stand.setChanged();

        progress.logEvent("Stage " + (currentStage + 1) + "/" + stages.size() + ": loaded " + stage.ingredientId);
        waitTicks = 0;
        enterPhase(Phase.WAITING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickWaiting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        waitTicks++;

        if (waitTicks > MAX_WAIT_TICKS) {
            enterPhase(Phase.COLLECT_STAGE);
            return BehaviorResult.RUNNING;
        }

        if (player.level().getBlockEntity(standPos) instanceof BrewingStandBlockEntity stand) {
            // Ingredient consumed = stage done
            if (stand.getItem(3).isEmpty() && waitTicks > 20) {
                enterPhase(Phase.COLLECT_STAGE);
            }
        } else {
            progress.setFailureReason("Brewing stand disappeared during brewing");
            return BehaviorResult.FAILED;
        }

        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCollectStage(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        currentStage++;

        if (currentStage >= stages.size()) {
            // Final stage done — collect finished potions
            if (player.level().getBlockEntity(standPos) instanceof BrewingStandBlockEntity stand) {
                int collected = 0;
                for (int i = 0; i < 3; i++) {
                    ItemStack item = stand.getItem(i);
                    if (!item.isEmpty()) {
                        player.getInventory().add(item.copy());
                        stand.setItem(i, ItemStack.EMPTY);
                        collected++;
                    }
                }
                stand.setChanged();
                progress.increment("potions_brewed", collected);
                progress.logEvent("Brewing complete: collected " + collected + " potion(s)");
            }
            return BehaviorResult.SUCCESS;
        }

        // More stages — potions stay in the stand, load next ingredient
        progress.logEvent("Stage " + currentStage + " done, preparing next");
        enterPhase(Phase.LOAD_STAGE);
        return BehaviorResult.RUNNING;
    }

    private int findItemSlot(ServerPlayer player, String itemId) {
        String search = itemId.toLowerCase().replace("minecraft:", "");
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
            if (id.contains(search)) return i;
        }
        return -1;
    }

    private int findWaterBottleSlot(ServerPlayer player) {
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            if (stack.getItem() == Items.POTION) {
                // Check if it's a water bottle (no effects)
                var potionContents = stack.get(net.minecraft.core.component.DataComponents.POTION_CONTENTS);
                if (potionContents != null && potionContents.potion().isPresent()) {
                    var potion = potionContents.potion().get();
                    if (potion == net.minecraft.world.item.alchemy.Potions.WATER) {
                        return i;
                    }
                }
            }
        }
        return -1;
    }

    private int countBottles(ServerPlayer player) {
        int count = 0;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            if (stack.getItem() == Items.POTION) {
                var potionContents = stack.get(net.minecraft.core.component.DataComponents.POTION_CONTENTS);
                if (potionContents != null && potionContents.potion().isPresent()) {
                    var potion = potionContents.potion().get();
                    if (potion == net.minecraft.world.item.alchemy.Potions.WATER) {
                        count++;
                    }
                }
            }
        }
        return count;
    }

    private BlockPos findNearbyBlock(ServerPlayer player, String blockName, int radius) {
        BlockPos center = player.blockPosition();
        BlockPos nearest = null;
        double nearestDist = Double.MAX_VALUE;
        for (int dx = -radius; dx <= radius; dx++) {
            for (int dy = -radius; dy <= radius; dy++) {
                for (int dz = -radius; dz <= radius; dz++) {
                    BlockPos pos = center.offset(dx, dy, dz);
                    String id = BuiltInRegistries.BLOCK.getKey(
                            player.level().getBlockState(pos).getBlock()).getPath();
                    if (id.contains(blockName)) {
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

    private void enterPhase(Phase p) {
        this.phase = p;
        progress.setPhase(p.name().toLowerCase());
    }

    @Override
    public String describeState() {
        return switch (phase) {
            case RESOLVE -> "Resolving potion recipe for " + targetPotion;
            case FIND_STAND -> "Looking for brewing stand";
            case NAVIGATE -> "Moving to brewing stand";
            case CHECK_FUEL -> "Checking fuel";
            case LOAD_STAGE -> "Loading stage " + (currentStage + 1) + "/" + (stages != null ? stages.size() : 0);
            case WAITING -> "Brewing stage " + (currentStage + 1) + " (" + waitTicks + " ticks)";
            case COLLECT_STAGE -> "Collecting stage " + currentStage;
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}

    private record BrewStage(String ingredientId) {}
}
