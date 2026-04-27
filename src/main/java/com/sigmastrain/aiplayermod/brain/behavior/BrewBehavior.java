package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.entity.BrewingStandBlockEntity;
import net.minecraft.world.phys.Vec3;

import java.util.*;

/**
 * L1 Brew behavior with self-healing:
 * 1. Resolve recipe chain
 * 2. Channel any missing ingredients, water bottles, blaze powder
 * 3. Find brewing stand (escalating search)
 * 4. Navigate, fuel, load, brew, collect
 */
public class BrewBehavior implements Behavior {
    private enum Phase {
        RESOLVE, CHANNEL_MATERIALS, FIND_STAND, NAVIGATE, CHECK_FUEL,
        CHANNEL_FUEL, LOAD_STAGE, WAITING, COLLECT_STAGE
    }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private String targetPotion;
    private int targetCount;
    private BlockPos standPos;

    private List<BrewStage> stages;
    private int currentStage;
    private int waitTicks;

    // Channeling state
    private List<ChannelRequest> channelQueue;
    private int channelIndex;
    private int channelTicks;
    private int channelXpCost;

    // Navigation
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;

    // Stand search escalation
    private static final int[] STAND_SEARCH_RADII = {32, 64, 128, 256};
    private int standRadiusIndex;

    private static final double REACH = 4.5;
    private static final int MAX_WAIT_TICKS = 500;
    private static final int CHANNEL_TICKS_PER_LEVEL = 5;

    private static final Map<String, List<String>> POTION_RECIPES = new LinkedHashMap<>();
    private static final Map<String, String> MODIFIERS = new LinkedHashMap<>();

    static {
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
        POTION_RECIPES.put("weakness",       List.of("minecraft:fermented_spider_eye"));
        POTION_RECIPES.put("slowness",       List.of("minecraft:nether_wart", "minecraft:sugar", "minecraft:fermented_spider_eye"));
        POTION_RECIPES.put("harming",        List.of("minecraft:nether_wart", "minecraft:glistering_melon_slice", "minecraft:fermented_spider_eye"));
        POTION_RECIPES.put("turtle_master",  List.of("minecraft:nether_wart", "minecraft:turtle_helmet"));

        MODIFIERS.put("long",     "minecraft:redstone");
        MODIFIERS.put("strong",   "minecraft:glowstone_dust");
        MODIFIERS.put("splash",   "minecraft:gunpowder");
        MODIFIERS.put("lingering","minecraft:dragon_breath");
    }

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.targetPotion = directive.getTarget();
        this.targetCount = directive.getCount() > 0 ? Math.min(directive.getCount(), 3) : 3;
        this.stages = new ArrayList<>();
        this.currentStage = 0;
        this.channelQueue = new ArrayList<>();
        this.channelIndex = 0;
        this.standRadiusIndex = 0;
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        enterPhase(Phase.RESOLVE);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case RESOLVE -> tickResolve(bot);
            case CHANNEL_MATERIALS -> tickChanneling(bot);
            case FIND_STAND -> tickFindStand(bot);
            case NAVIGATE -> tickNavigate(bot);
            case CHECK_FUEL -> tickCheckFuel(bot);
            case CHANNEL_FUEL -> tickChannelFuel(bot);
            case LOAD_STAGE -> tickLoadStage(bot);
            case WAITING -> tickWaiting(bot);
            case COLLECT_STAGE -> tickCollectStage(bot);
        };
    }

    private BehaviorResult tickResolve(BotPlayer bot) {
        String potionName = targetPotion.toLowerCase()
                .replace("minecraft:", "")
                .replace("potion_of_", "")
                .replace("potion of ", "")
                .replace("_potion", "")
                .replace(" potion", "")
                .trim();

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

        // Identify all missing materials and queue channeling
        ServerPlayer player = bot.getPlayer();
        channelQueue.clear();

        for (BrewStage stage : stages) {
            if (findItemSlot(player, stage.ingredientId) < 0) {
                channelQueue.add(new ChannelRequest(stage.ingredientId, 1));
            }
        }

        int bottleCount = countWaterBottles(player);
        if (bottleCount < targetCount) {
            int needed = targetCount - bottleCount;
            channelQueue.add(new ChannelRequest("minecraft:potion", needed));
        }

        // Check blaze powder (need at least 1 for fuel)
        if (findItemSlot(player, "minecraft:blaze_powder") < 0) {
            channelQueue.add(new ChannelRequest("minecraft:blaze_powder", 1));
        }

        if (!channelQueue.isEmpty()) {
            channelIndex = 0;
            startNextChannel(player);
            bot.systemChat("Channeling " + channelQueue.size() + " missing brewing material(s)...", "light_purple");
            enterPhase(Phase.CHANNEL_MATERIALS);
            return BehaviorResult.RUNNING;
        }

        standRadiusIndex = 0;
        enterPhase(Phase.FIND_STAND);
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

        ChannelRequest req = channelQueue.get(channelIndex);

        if (req.itemId.equals("minecraft:potion")) {
            // Channel water bottles
            for (int i = 0; i < req.count; i++) {
                ItemStack waterBottle = new ItemStack(Items.POTION, 1);
                waterBottle.set(net.minecraft.core.component.DataComponents.POTION_CONTENTS,
                        new net.minecraft.world.item.alchemy.PotionContents(net.minecraft.world.item.alchemy.Potions.WATER));
                player.getInventory().add(waterBottle);
            }
        } else {
            Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(req.itemId));
            if (item == Items.AIR) {
                progress.setFailureReason("Channel failed: unknown item " + req.itemId);
                return BehaviorResult.FAILED;
            }
            player.getInventory().add(new ItemStack(item, req.count));
        }

        player.giveExperienceLevels(-channelXpCost);
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

        standRadiusIndex = 0;
        enterPhase(Phase.FIND_STAND);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickFindStand(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        int radius = STAND_SEARCH_RADII[Math.min(standRadiusIndex, STAND_SEARCH_RADII.length - 1)];
        standPos = findNearbyBlock(player, "brewing_stand", radius);

        if (standPos != null) {
            progress.logEvent("Found brewing stand at " + standPos.toShortString());
            enterPhase(Phase.NAVIGATE);
            return BehaviorResult.RUNNING;
        }

        standRadiusIndex++;
        if (standRadiusIndex < STAND_SEARCH_RADII.length) {
            progress.logEvent("Expanding stand search to " + STAND_SEARCH_RADII[standRadiusIndex] + " blocks");
            return BehaviorResult.RUNNING;
        }

        progress.setFailureReason("No brewing stand within " + STAND_SEARCH_RADII[STAND_SEARCH_RADII.length - 1] + " blocks");
        return BehaviorResult.FAILED;
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

        ItemStack existingFuel = stand.getItem(4);
        if (existingFuel.isEmpty()) {
            int blazeSlot = findItemSlot(player, "minecraft:blaze_powder");
            if (blazeSlot >= 0) {
                ItemStack fuel = player.getInventory().getItem(blazeSlot);
                stand.setItem(4, fuel.split(1));
                stand.setChanged();
                progress.logEvent("Loaded blaze powder as fuel");
            } else {
                // Channel blaze powder
                channelQueue.clear();
                channelQueue.add(new ChannelRequest("minecraft:blaze_powder", 1));
                channelIndex = 0;
                startNextChannel(player);
                bot.systemChat("Channeling blaze powder for fuel...", "light_purple");
                enterPhase(Phase.CHANNEL_FUEL);
                return BehaviorResult.RUNNING;
            }
        }

        enterPhase(Phase.LOAD_STAGE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickChannelFuel(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();

        if (channelTicks % 3 == 0) {
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 1.0, pos.z, 2, 0.8, 0.5, 0.8, 0.2);
        }

        channelTicks--;
        if (channelTicks > 0) return BehaviorResult.RUNNING;

        player.giveExperienceLevels(-channelXpCost);
        player.getInventory().add(new ItemStack(Items.BLAZE_POWDER, 1));
        progress.increment("items_channeled");
        progress.logEvent("Channeled blaze powder");

        level.sendParticles(ParticleTypes.END_ROD,
                pos.x, pos.y + 1.0, pos.z, 10, 0.5, 0.8, 0.5, 0.1);
        level.playSound(null, player.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.5f, 1.2f);

        enterPhase(Phase.CHECK_FUEL);
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

        if (currentStage == 0) {
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

        int ingredientSlot = findItemSlot(player, stage.ingredientId);
        if (ingredientSlot < 0) {
            // Channel the missing ingredient on the fly
            channelQueue.clear();
            channelQueue.add(new ChannelRequest(stage.ingredientId, 1));
            channelIndex = 0;
            startNextChannel(player);
            bot.systemChat("Channeling " + stage.ingredientId + "...", "light_purple");
            enterPhase(Phase.CHANNEL_MATERIALS);
            return BehaviorResult.RUNNING;
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

        progress.logEvent("Stage " + currentStage + " done, preparing next");
        enterPhase(Phase.LOAD_STAGE);
        return BehaviorResult.RUNNING;
    }

    // ── Channeling helpers ──

    private void startNextChannel(ServerPlayer player) {
        ChannelRequest req = channelQueue.get(channelIndex);
        channelXpCost = getConjureCost(req.itemId) * req.count;
        if (player.experienceLevel < channelXpCost) {
            int needed = channelXpCost - player.experienceLevel;
            player.giveExperienceLevels(needed);
            progress.logEvent("Meditated for " + needed + " XP levels");
        }
        channelTicks = Math.max(5, channelXpCost * CHANNEL_TICKS_PER_LEVEL);
        progress.logEvent("Channeling " + req.count + "x " + req.itemId + " (" + channelXpCost + " levels)");
    }

    private int getConjureCost(String itemId) {
        return switch (itemId) {
            case "minecraft:nether_wart", "minecraft:sugar", "minecraft:spider_eye",
                 "minecraft:gunpowder", "minecraft:redstone", "minecraft:glowstone_dust",
                 "minecraft:potion" -> 2;
            case "minecraft:golden_carrot", "minecraft:glistering_melon_slice",
                 "minecraft:fermented_spider_eye", "minecraft:magma_cream",
                 "minecraft:rabbit_foot", "minecraft:pufferfish" -> 4;
            case "minecraft:ghast_tear", "minecraft:blaze_powder",
                 "minecraft:phantom_membrane", "minecraft:turtle_helmet" -> 6;
            case "minecraft:dragon_breath" -> 10;
            default -> 5;
        };
    }

    // ── Inventory helpers ──

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

    private int countWaterBottles(ServerPlayer player) {
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
            case CHANNEL_MATERIALS -> "Channeling brewing ingredients";
            case FIND_STAND -> "Looking for brewing stand";
            case NAVIGATE -> "Moving to brewing stand";
            case CHECK_FUEL -> "Checking fuel";
            case CHANNEL_FUEL -> "Channeling blaze powder";
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
    private record ChannelRequest(String itemId, int count) {}
}
