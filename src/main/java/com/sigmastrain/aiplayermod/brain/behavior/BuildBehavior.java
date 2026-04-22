package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;

import java.util.*;

/**
 * Places blocks from inventory following a predefined blueprint.
 * Directive target = blueprint name (shelter, wall, farm, tower, platform).
 * Directive extra "material" = block registry ID (default: cobblestone).
 * Uses the bot's current position as the build origin.
 */
public class BuildBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();

    private List<int[]> blueprint; // relative offsets [dx, dy, dz]
    private String materialId;
    private BlockPos origin;
    private int placeIndex;
    private int placeCooldown;
    private int blocksPlaced;
    private int totalBlocks;
    private String blueprintName;

    private static final int PLACE_INTERVAL = 4; // ticks between placements
    private static final int MAX_REACH = 6;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("preparing");

        blueprintName = directive.getTarget() != null ? directive.getTarget().toLowerCase() : "shelter";
        materialId = directive.getExtra().getOrDefault("material", "minecraft:cobblestone");
        if (!materialId.contains(":")) materialId = "minecraft:" + materialId;

        blueprint = getBlueprint(blueprintName);
        if (blueprint == null) {
            progress.setFailureReason("Unknown blueprint: " + blueprintName
                    + ". Available: shelter, wall, farm, tower, platform");
            return;
        }

        ServerPlayer player = bot.getPlayer();
        origin = player.blockPosition().relative(Direction.fromYRot(player.getYRot()), 2);
        placeIndex = 0;
        placeCooldown = 0;
        blocksPlaced = 0;
        totalBlocks = blueprint.size();

        progress.logEvent("Building " + blueprintName + " with " + materialId
                + " (" + totalBlocks + " blocks)");
        bot.systemChat("Building " + blueprintName + " (" + totalBlocks + " blocks)", "aqua");
        AIPlayerMod.LOGGER.info("[{}] BUILD {} at {} with {} ({} blocks)",
                player.getName().getString(), blueprintName, origin, materialId, totalBlocks);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (progress.toMap().containsKey("failure_reason")) {
            return BehaviorResult.FAILED;
        }

        if (placeIndex >= blueprint.size()) {
            progress.logEvent("Build complete: " + blocksPlaced + "/" + totalBlocks + " placed");
            bot.systemChat("Built " + blueprintName + " (" + blocksPlaced + " blocks)", "green");
            return BehaviorResult.SUCCESS;
        }

        if (placeCooldown > 0) {
            placeCooldown--;
            return BehaviorResult.RUNNING;
        }

        progress.setPhase("building (" + placeIndex + "/" + totalBlocks + ")");

        ServerPlayer player = bot.getPlayer();
        int[] offset = blueprint.get(placeIndex);
        BlockPos target = origin.offset(offset[0], offset[1], offset[2]);

        BlockState existing = player.level().getBlockState(target);
        if (!existing.isAir() && !existing.canBeReplaced()) {
            placeIndex++;
            return BehaviorResult.RUNNING;
        }

        int slot = findMaterialSlot(player);
        if (slot < 0) {
            progress.setFailureReason("Out of " + materialId + " (" + blocksPlaced + "/" + totalBlocks + " placed)");
            return BehaviorResult.FAILED;
        }

        int prevSelected = player.getInventory().selected;
        if (slot < 9) {
            player.getInventory().selected = slot;
        } else {
            ItemStack hotbar = player.getInventory().getItem(0);
            ItemStack material = player.getInventory().getItem(slot);
            player.getInventory().setItem(0, material);
            player.getInventory().setItem(slot, hotbar);
            player.getInventory().selected = 0;
        }

        bot.lookAt(target.getX() + 0.5, target.getY() + 0.5, target.getZ() + 0.5);

        ItemStack held = player.getMainHandItem();
        if (held.getItem() instanceof BlockItem blockItem) {
            BlockHitResult hit = new BlockHitResult(
                    Vec3.atCenterOf(target), Direction.UP, target, false);
            UseOnContext ctx = new UseOnContext(player, InteractionHand.MAIN_HAND, hit);
            blockItem.useOn(ctx);
            blocksPlaced++;
            progress.increment("blocks_placed");
        }

        if (slot >= 9) {
            player.getInventory().selected = prevSelected;
        }

        placeIndex++;
        placeCooldown = PLACE_INTERVAL;
        return BehaviorResult.RUNNING;
    }

    private int findMaterialSlot(ServerPlayer player) {
        Item target = BuiltInRegistries.ITEM.get(ResourceLocation.parse(materialId));
        for (int i = 0; i < 36; i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty() && s.is(target)) return i;
        }
        // Fallback: any block item in inventory
        for (int i = 0; i < 36; i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty() && s.getItem() instanceof BlockItem) return i;
        }
        return -1;
    }

    private static List<int[]> getBlueprint(String name) {
        return switch (name) {
            case "shelter" -> buildShelter();
            case "wall" -> buildWall();
            case "farm" -> buildFarm();
            case "tower" -> buildTower();
            case "platform" -> buildPlatform();
            default -> null;
        };
    }

    // 5x5x4 enclosed shelter with door gap
    private static List<int[]> buildShelter() {
        List<int[]> blocks = new ArrayList<>();
        // Floor
        for (int x = 0; x < 5; x++)
            for (int z = 0; z < 5; z++)
                blocks.add(new int[]{x, -1, z});
        // Walls (3 high)
        for (int y = 0; y < 3; y++) {
            for (int x = 0; x < 5; x++) {
                blocks.add(new int[]{x, y, 0});
                blocks.add(new int[]{x, y, 4});
            }
            for (int z = 1; z < 4; z++) {
                blocks.add(new int[]{0, y, z});
                if (!(y < 2 && z == 2)) { // door gap on front wall
                    blocks.add(new int[]{4, y, z});
                }
            }
        }
        // Roof
        for (int x = 0; x < 5; x++)
            for (int z = 0; z < 5; z++)
                blocks.add(new int[]{x, 3, z});
        return blocks;
    }

    // 9-long, 3-high wall
    private static List<int[]> buildWall() {
        List<int[]> blocks = new ArrayList<>();
        for (int x = 0; x < 9; x++)
            for (int y = 0; y < 3; y++)
                blocks.add(new int[]{x, y, 0});
        return blocks;
    }

    // 7x7 tilled farm area with water center (just the border + rows)
    private static List<int[]> buildFarm() {
        List<int[]> blocks = new ArrayList<>();
        // Border
        for (int x = 0; x < 7; x++) {
            blocks.add(new int[]{x, 0, 0});
            blocks.add(new int[]{x, 0, 6});
        }
        for (int z = 1; z < 6; z++) {
            blocks.add(new int[]{0, 0, z});
            blocks.add(new int[]{6, 0, z});
        }
        // Row markers at y=0 (interior)
        for (int x = 1; x < 6; x++)
            for (int z = 1; z < 6; z++)
                blocks.add(new int[]{x, -1, z});
        return blocks;
    }

    // 3x3 tower, 8 high with interior ladder space
    private static List<int[]> buildTower() {
        List<int[]> blocks = new ArrayList<>();
        for (int y = 0; y < 8; y++) {
            for (int x = 0; x < 3; x++) {
                for (int z = 0; z < 3; z++) {
                    if (x == 1 && z == 1) continue; // hollow interior
                    blocks.add(new int[]{x, y, z});
                }
            }
        }
        // Cap
        for (int x = 0; x < 3; x++)
            for (int z = 0; z < 3; z++)
                blocks.add(new int[]{x, 8, z});
        return blocks;
    }

    // 7x7 flat platform
    private static List<int[]> buildPlatform() {
        List<int[]> blocks = new ArrayList<>();
        for (int x = 0; x < 7; x++)
            for (int z = 0; z < 7; z++)
                blocks.add(new int[]{x, 0, z});
        return blocks;
    }

    @Override
    public String describeState() {
        return "Building " + blueprintName + " (" + blocksPlaced + "/" + totalBlocks + ")";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
