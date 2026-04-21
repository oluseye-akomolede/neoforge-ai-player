package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.inventory.ContainerLevelAccess;
import net.minecraft.world.inventory.EnchantmentMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.enchantment.EnchantmentHelper;
import net.minecraft.world.phys.Vec3;

/**
 * Composite enchanting behavior:
 * 1. Find enchanting table nearby (won't auto-craft — too expensive)
 * 2. Navigate to it
 * 3. Check XP — meditate if too low
 * 4. Find item + lapis in inventory
 * 5. Execute enchantment
 */
public class EnchantBehavior implements Behavior {
    private enum Phase {
        FIND_TABLE, NAVIGATE, CHECK_XP, MEDITATING, FIND_MATERIALS, ENCHANTING
    }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private BlockPos tablePos;
    private int option;
    private int itemSlot = -1;
    private int lapisSlot = -1;
    private String targetItem;

    // Meditation state
    private int meditateTarget;
    private int meditateTicks;
    private int meditateLevelsGained;
    private static final int TICKS_PER_LEVEL = 40;

    // Navigation
    private double yVelocity;
    private int ticksStuck;
    private Vec3 lastPos;

    private static final double REACH = 4.5;
    private static final int TABLE_SEARCH_RADIUS = 24;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.targetItem = directive.getTarget();
        this.option = 2;
        if (directive.getExtra().containsKey("option")) {
            try { this.option = Integer.parseInt(directive.getExtra().get("option")); }
            catch (NumberFormatException ignored) {}
        }
        this.option = Math.max(0, Math.min(2, this.option));
        this.yVelocity = 0;
        this.ticksStuck = 0;
        this.lastPos = null;
        enterPhase(Phase.FIND_TABLE);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case FIND_TABLE -> tickFindTable(bot);
            case NAVIGATE -> tickNavigate(bot);
            case CHECK_XP -> tickCheckXp(bot);
            case MEDITATING -> tickMeditating(bot);
            case FIND_MATERIALS -> tickFindMaterials(bot);
            case ENCHANTING -> tickEnchanting(bot);
        };
    }

    private BehaviorResult tickFindTable(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        tablePos = findNearbyBlock(player, "enchanting_table", TABLE_SEARCH_RADIUS);
        if (tablePos == null) {
            progress.setFailureReason("No enchanting table within " + TABLE_SEARCH_RADIUS + " blocks");
            return BehaviorResult.FAILED;
        }
        progress.logEvent("Found enchanting table at " + tablePos.toShortString());
        enterPhase(Phase.NAVIGATE);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickNavigate(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Vec3 target = Vec3.atCenterOf(tablePos);
        double dist = player.position().distanceTo(target);

        if (dist <= REACH) {
            enterPhase(Phase.CHECK_XP);
            return BehaviorResult.RUNNING;
        }

        moveToward(bot, player, target, dist);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickCheckXp(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        // We need at least option+1 levels (1 for cheapest, 3 for best)
        // But the actual cost depends on the enchantment offered, which varies.
        // Use a safe minimum: option 0 needs ~1-8, option 1 needs ~5-15, option 2 needs ~10-30
        int minLevels = switch (option) {
            case 0 -> 1;
            case 1 -> 8;
            default -> 30;
        };

        if (player.experienceLevel >= minLevels) {
            progress.logEvent("Have " + player.experienceLevel + " XP levels (need ~" + minLevels + ")");
            enterPhase(Phase.FIND_MATERIALS);
            return BehaviorResult.RUNNING;
        }

        meditateTarget = minLevels - player.experienceLevel;
        meditateTicks = 0;
        meditateLevelsGained = 0;
        progress.logEvent("Need " + meditateTarget + " more XP levels, meditating");
        bot.systemChat("Meditating for " + meditateTarget + " XP levels...", "light_purple");
        enterPhase(Phase.MEDITATING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickMeditating(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        meditateTicks++;

        if (meditateTicks % 4 == 0) {
            Vec3 pos = player.position();
            level.sendParticles(net.minecraft.core.particles.ParticleTypes.ENCHANT,
                    pos.x, pos.y + 1.5, pos.z, 3, 0.5, 0.5, 0.5, 0.1);
        }

        if (meditateTicks % TICKS_PER_LEVEL == 0) {
            player.giveExperienceLevels(1);
            meditateLevelsGained++;
            progress.increment("xp_levels_gained");

            if (meditateLevelsGained >= meditateTarget) {
                progress.logEvent("Meditation complete: gained " + meditateLevelsGained + " levels");
                enterPhase(Phase.FIND_MATERIALS);
            }
        }
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickFindMaterials(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        // Find lapis
        lapisSlot = -1;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty() && stack.getItem() == Items.LAPIS_LAZULI && stack.getCount() >= option + 1) {
                lapisSlot = i;
                break;
            }
        }
        if (lapisSlot < 0) {
            progress.setFailureReason("No lapis lazuli in inventory (need " + (option + 1) + ")");
            return BehaviorResult.FAILED;
        }

        // Find enchantable item
        itemSlot = -1;
        if (targetItem != null && !targetItem.isEmpty()) {
            // Target specified — find by item ID or slot number
            try {
                int slot = Integer.parseInt(targetItem);
                ItemStack stack = player.getInventory().getItem(slot);
                if (!stack.isEmpty() && stack.isEnchantable()) {
                    itemSlot = slot;
                }
            } catch (NumberFormatException e) {
                String search = targetItem.toLowerCase();
                for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
                    ItemStack stack = player.getInventory().getItem(i);
                    if (stack.isEmpty() || !stack.isEnchantable()) continue;
                    String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
                    if (id.contains(search)) {
                        itemSlot = i;
                        break;
                    }
                }
            }
        }

        if (itemSlot < 0) {
            // Fall back: find any enchantable item (tools, weapons, armor)
            for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
                ItemStack stack = player.getInventory().getItem(i);
                if (!stack.isEmpty() && stack.isEnchantable()) {
                    itemSlot = i;
                    break;
                }
            }
        }

        if (itemSlot < 0) {
            progress.setFailureReason("No enchantable item found in inventory");
            return BehaviorResult.FAILED;
        }

        String itemId = BuiltInRegistries.ITEM.getKey(player.getInventory().getItem(itemSlot).getItem()).toString();
        progress.logEvent("Enchanting " + itemId + " (slot " + itemSlot + ") with option " + option);
        enterPhase(Phase.ENCHANTING);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickEnchanting(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        ItemStack item = player.getInventory().getItem(itemSlot);
        ItemStack lapis = player.getInventory().getItem(lapisSlot);

        if (item.isEmpty()) {
            progress.setFailureReason("Item disappeared from slot " + itemSlot);
            return BehaviorResult.FAILED;
        }
        if (lapis.isEmpty() || lapis.getItem() != Items.LAPIS_LAZULI) {
            progress.setFailureReason("Lapis disappeared from slot " + lapisSlot);
            return BehaviorResult.FAILED;
        }

        ContainerLevelAccess access = ContainerLevelAccess.create(player.level(), tablePos);
        EnchantmentMenu menu = new EnchantmentMenu(
                player.containerMenu.containerId + 1, player.getInventory(), access);

        menu.getSlot(0).set(item.copy());
        menu.getSlot(1).set(lapis.copy());
        menu.slotsChanged(menu.getSlot(0).container);

        if (menu.costs[option] <= 0) {
            // Try lower options
            int usedOption = -1;
            for (int o = option; o >= 0; o--) {
                if (menu.costs[o] > 0) {
                    usedOption = o;
                    break;
                }
            }
            if (usedOption < 0) {
                progress.setFailureReason("No enchantment options available for this item");
                menu.removed(player);
                return BehaviorResult.FAILED;
            }
            option = usedOption;
        }

        if (player.experienceLevel < menu.costs[option]) {
            progress.setFailureReason("Not enough XP: need " + menu.costs[option] + " but have " + player.experienceLevel);
            menu.removed(player);
            return BehaviorResult.FAILED;
        }

        if (menu.clickMenuButton(player, option)) {
            ItemStack enchanted = menu.getSlot(0).getItem();
            player.getInventory().setItem(itemSlot, enchanted.copy());
            player.getInventory().getItem(lapisSlot).shrink(option + 1);
            progress.increment("items_enchanted");
            progress.logEvent("Enchanted successfully (cost " + menu.costs[option] + " levels)");
            menu.removed(player);
            return BehaviorResult.SUCCESS;
        }

        menu.removed(player);
        progress.setFailureReason("Enchantment application failed");
        return BehaviorResult.FAILED;
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
            case FIND_TABLE -> "Looking for enchanting table";
            case NAVIGATE -> "Moving to enchanting table";
            case CHECK_XP -> "Checking XP levels";
            case MEDITATING -> "Meditating for XP (" + meditateLevelsGained + "/" + meditateTarget + ")";
            case FIND_MATERIALS -> "Finding item and lapis";
            case ENCHANTING -> "Enchanting item";
        };
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
