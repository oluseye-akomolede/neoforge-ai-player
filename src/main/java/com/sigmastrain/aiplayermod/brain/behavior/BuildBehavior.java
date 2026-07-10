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
 * Directive target = blueprint name (shelter, wall, farm, tower, platform);
 * extra "shape" is accepted as a fallback, and common synonyms (pillar,
 * gate, cube, keep, ...) map onto the real blueprints.
 * Directive extra "material" = block registry ID (default: cobblestone).
 * Directive x/y/z (if non-zero) = build origin; otherwise the bot's position.
 * Extra "size"/"length"/"width" and "height" parameterize wall/tower/platform.
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

    // L3 vocabulary → real blueprints (war-game finding B1: L3 invents shapes)
    private static final Map<String, String> BLUEPRINT_ALIASES = Map.of(
            "pillar", "tower",
            "watchtower", "tower",
            "gate", "wall",
            "door", "wall",
            "cube", "shelter",
            "keep", "shelter",
            "house", "shelter",
            "fortress", "shelter",
            "excavate", "clear",
            "dig", "clear");

    // "clear" excavates instead of placing (finding 21 follow-up: structures
    // must be built in a cleared pocket, not embedded in solid terrain).
    private boolean clearMode;
    private static final int CLEAR_BLOCKS_PER_TICK = 16;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("preparing");

        // Blueprint name: target field, else extra "shape" (the form L3 tends
        // to emit), else default shelter. Resolve synonyms onto real blueprints.
        String rawName = directive.getTarget() != null && !directive.getTarget().isEmpty()
                ? directive.getTarget()
                : directive.getExtra().getOrDefault("shape", "shelter");
        blueprintName = rawName.toLowerCase();
        if (BLUEPRINT_ALIASES.containsKey(blueprintName)) {
            AIPlayerMod.LOGGER.info("[{}] BUILD blueprint '{}' aliased to '{}'",
                    bot.getPlayer().getName().getString(), blueprintName,
                    BLUEPRINT_ALIASES.get(blueprintName));
            blueprintName = BLUEPRINT_ALIASES.get(blueprintName);
        }
        materialId = directive.getExtra().getOrDefault("material", "minecraft:cobblestone");
        if (!materialId.contains(":")) materialId = "minecraft:" + materialId;

        int size = parseIntExtra(directive, 0, "size", "length", "width");
        int height = parseIntExtra(directive, 0, "height");
        clearMode = "clear".equals(blueprintName);
        blueprint = clearMode
                ? buildClearVolume(clamp(size, 3, 32, 23), clamp(height, 3, 24, 12))
                : getBlueprint(blueprintName, size, height);
        if (blueprint == null) {
            progress.setFailureReason("Unknown blueprint: " + blueprintName
                    + ". Available: shelter, wall, farm, tower, platform, clear");
            return;
        }

        ServerPlayer player = bot.getPlayer();
        // Explicit directive coordinates win; all-zero means "build here".
        double dx = directive.getX(), dy = directive.getY(), dz = directive.getZ();
        if (dx != 0 || dy != 0 || dz != 0) {
            origin = new BlockPos((int) dx, (int) dy, (int) dz);
            // Stand adjacent to the origin so the build is attended.
            bot.teleport(dx - 2, dy, dz - 2);
        } else {
            origin = player.blockPosition().relative(Direction.fromYRot(player.getYRot()), 2);
        }
        placeIndex = 0;
        placeCooldown = 0;
        blocksPlaced = 0;
        totalBlocks = blueprint.size();

        progress.logEvent("Building " + blueprintName + " at " + origin.toShortString()
                + " with " + materialId + " (" + totalBlocks + " blocks)");
        bot.systemChat("Building " + blueprintName + " (" + totalBlocks + " blocks)", "aqua");
        AIPlayerMod.LOGGER.info("[{}] BUILD {} at {} with {} ({} blocks)",
                player.getName().getString(), blueprintName, origin, materialId, totalBlocks);
    }

    private static int parseIntExtra(Directive directive, int fallback, String... keys) {
        for (String key : keys) {
            String v = directive.getExtra().get(key);
            if (v != null) {
                try {
                    return Integer.parseInt(v.trim());
                } catch (NumberFormatException ignored) {
                }
            }
        }
        return fallback;
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (progress.toMap().containsKey("failure_reason")) {
            return BehaviorResult.FAILED;
        }

        if (placeIndex >= blueprint.size()) {
            String verb = clearMode ? "cleared" : "placed";
            progress.logEvent("Build complete: " + blocksPlaced + "/" + totalBlocks + " " + verb);
            bot.systemChat((clearMode ? "Cleared " : "Built ") + blueprintName
                    + " (" + blocksPlaced + " blocks)", "green");
            return BehaviorResult.SUCCESS;
        }

        if (placeCooldown > 0) {
            placeCooldown--;
            return BehaviorResult.RUNNING;
        }

        ServerPlayer player = bot.getPlayer();

        if (clearMode) {
            progress.setPhase("clearing (" + placeIndex + "/" + totalBlocks + ")");
            var level = player.serverLevel();
            int processed = 0;
            while (placeIndex < blueprint.size() && processed < CLEAR_BLOCKS_PER_TICK) {
                int[] off = blueprint.get(placeIndex);
                BlockPos pos = origin.offset(off[0], off[1], off[2]);
                BlockState st = level.getBlockState(pos);
                if (!st.isAir() && st.getDestroySpeed(level, pos) >= 0) {
                    level.destroyBlock(pos, false);
                    blocksPlaced++;
                }
                placeIndex++;
                processed++;
            }
            placeCooldown = 1;
            return BehaviorResult.RUNNING;
        }

        progress.setPhase("building (" + placeIndex + "/" + totalBlocks + ")");

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

    private static List<int[]> getBlueprint(String name, int size, int height) {
        return switch (name) {
            case "shelter" -> buildShelter();
            case "wall" -> buildWall(clamp(size, 3, 64, 9), clamp(height, 1, 16, 3));
            case "farm" -> buildFarm();
            case "tower" -> buildTower(clamp(height > 0 ? height : size, 3, 32, 8));
            case "platform" -> buildPlatform(clamp(size, 3, 32, 7));
            default -> null;
        };
    }

    private static int clamp(int v, int min, int max, int fallback) {
        if (v <= 0) return fallback;
        return Math.max(min, Math.min(max, v));
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

    // Parametric wall: length blocks long, height blocks high
    private static List<int[]> buildWall(int length, int height) {
        List<int[]> blocks = new ArrayList<>();
        for (int x = 0; x < length; x++)
            for (int y = 0; y < height; y++)
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

    // 3x3 tower, parametric height, with interior ladder space
    private static List<int[]> buildTower(int height) {
        List<int[]> blocks = new ArrayList<>();
        for (int y = 0; y < height; y++) {
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
                blocks.add(new int[]{x, height, z});
        return blocks;
    }

    // Excavation volume: size x height x size, bottom-up from origin
    private static List<int[]> buildClearVolume(int size, int height) {
        List<int[]> blocks = new ArrayList<>();
        for (int y = 0; y < height; y++)
            for (int x = 0; x < size; x++)
                for (int z = 0; z < size; z++)
                    blocks.add(new int[]{x, y, z});
        return blocks;
    }

    // Parametric flat platform (size x size)
    private static List<int[]> buildPlatform(int size) {
        List<int[]> blocks = new ArrayList<>();
        for (int x = 0; x < size; x++)
            for (int z = 0; z < size; z++)
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
