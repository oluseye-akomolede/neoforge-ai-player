package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.*;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.Container;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.neoforged.neoforge.capabilities.Capabilities;
import net.neoforged.neoforge.items.IItemHandler;
import net.neoforged.neoforge.items.ItemHandlerHelper;

import java.util.*;

public class StoreAllBehavior implements Behavior {
    private enum Phase { VALIDATE, SCAN_INVENTORY, FIND_CONTAINER, DEPOSITING, NEXT_ITEM, CONJURING, COMPLETE }

    private final ProgressReport progress = new ProgressReport();
    private Phase phase;

    private List<ItemEntry> itemsToStore;
    private int currentItemIdx;
    private int totalStored;

    private boolean keepFood = true;
    private boolean keepTools = true;
    private Set<String> keepItems = new HashSet<>();

    private List<ContainerRegistry.ContainerEntry> candidates;
    private int candidateIdx;
    private ContainerRegistry.ContainerEntry currentContainer;

    private BlockPos placePos;
    private int placeTicks;
    private static final int PLACE_TICKS = 40;
    private static final int PLACE_XP_COST = 3;

    private record ItemEntry(Item item, String itemId, int count) {}

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        totalStored = 0;
        currentItemIdx = 0;
        candidateIdx = 0;

        Map<String, String> extra = directive.getExtra();
        if (extra != null) {
            if ("false".equalsIgnoreCase(extra.get("keep_food"))) keepFood = false;
            if ("false".equalsIgnoreCase(extra.get("keep_tools"))) keepTools = false;
            String keepList = extra.get("keep_items");
            if (keepList != null && !keepList.isEmpty()) {
                for (String id : keepList.split(",")) {
                    String trimmed = id.trim();
                    if (!trimmed.contains(":")) trimmed = "minecraft:" + trimmed;
                    keepItems.add(trimmed);
                }
            }
        }

        phase = Phase.SCAN_INVENTORY;
        bot.systemChat("Storing all non-essential items...", "aqua");
        progress.logEvent("Store all initiated");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return switch (phase) {
            case VALIDATE -> BehaviorResult.FAILED;
            case SCAN_INVENTORY -> tickScanInventory(bot);
            case FIND_CONTAINER -> tickFindContainer(bot);
            case DEPOSITING -> tickDepositing(bot);
            case NEXT_ITEM -> tickNextItem(bot);
            case CONJURING -> tickConjuring(bot);
            case COMPLETE -> BehaviorResult.SUCCESS;
        };
    }

    private BehaviorResult tickScanInventory(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Map<Item, Integer> grouped = new LinkedHashMap<>();

        int selectedSlot = player.getInventory().selected;

        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            if (isEssential(player, stack, i, selectedSlot)) continue;

            grouped.merge(stack.getItem(), stack.getCount(), Integer::sum);
        }

        if (grouped.isEmpty()) {
            progress.logEvent("No non-essential items to store");
            bot.systemChat("Nothing to store — inventory is all essentials", "yellow");
            return BehaviorResult.SUCCESS;
        }

        itemsToStore = new ArrayList<>();
        for (var entry : grouped.entrySet()) {
            String itemId = BuiltInRegistries.ITEM.getKey(entry.getKey()).toString();
            itemsToStore.add(new ItemEntry(entry.getKey(), itemId, entry.getValue()));
        }

        progress.logEvent("Found " + itemsToStore.size() + " item types to store (" +
                grouped.values().stream().mapToInt(Integer::intValue).sum() + " total items)");
        bot.systemChat("Storing " + itemsToStore.size() + " item types", "aqua");

        String dimension = player.serverLevel().dimension().location().toString();
        candidates = ContainerRegistry.get().getByDimension(dimension);
        candidateIdx = 0;
        currentItemIdx = 0;
        phase = Phase.FIND_CONTAINER;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickFindContainer(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        while (candidateIdx < candidates.size()) {
            ContainerRegistry.ContainerEntry entry = candidates.get(candidateIdx);

            if (!isStorageBlock(level, entry.pos())) {
                ContainerRegistry.get().remove(entry.id());
                candidateIdx++;
                continue;
            }

            if (hasAnySpace(level, entry.pos())) {
                currentContainer = entry;
                player.moveTo(entry.pos().getX() + 0.5, entry.pos().getY(), entry.pos().getZ() + 0.5);
                phase = Phase.DEPOSITING;
                return BehaviorResult.RUNNING;
            }
            candidateIdx++;
        }

        enterConjuring(bot);
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickDepositing(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        BlockPos pos = currentContainer != null ? currentContainer.pos() : placePos;

        if (!isStorageBlock(level, pos)) {
            candidateIdx++;
            phase = Phase.FIND_CONTAINER;
            return BehaviorResult.RUNNING;
        }

        ItemEntry current = itemsToStore.get(currentItemIdx);
        int selectedSlot = player.getInventory().selected;
        int deposited = 0;

        IItemHandler handler = level.getCapability(Capabilities.ItemHandler.BLOCK, pos, null);
        if (handler != null) {
            deposited = depositViaHandler(player, handler, current.item, selectedSlot);
        } else {
            BlockEntity be = level.getBlockEntity(pos);
            if (be instanceof Container container) {
                deposited = depositViaContainer(player, container, current.item, selectedSlot);
                container.setChanged();
            }
        }

        totalStored += deposited;

        if (deposited > 0) {
            progress.logEvent("Stored " + deposited + "x " + current.itemId);
        }

        phase = Phase.NEXT_ITEM;
        return BehaviorResult.RUNNING;
    }

    private int depositViaHandler(ServerPlayer player, IItemHandler handler, Item targetItem, int selectedSlot) {
        int moved = 0;
        for (int invSlot = 0; invSlot < player.getInventory().getContainerSize(); invSlot++) {
            ItemStack stack = player.getInventory().getItem(invSlot);
            if (stack.isEmpty() || !stack.is(targetItem)) continue;
            if (isEssential(player, stack, invSlot, selectedSlot)) continue;

            ItemStack toInsert = stack.copy();
            ItemStack leftover = ItemHandlerHelper.insertItemStacked(handler, toInsert, false);
            int accepted = toInsert.getCount() - leftover.getCount();
            if (accepted > 0) {
                stack.shrink(accepted);
                moved += accepted;
            }
            if (!leftover.isEmpty()) break;
        }
        return moved;
    }

    private int depositViaContainer(ServerPlayer player, Container container, Item targetItem, int selectedSlot) {
        int moved = 0;
        for (int invSlot = 0; invSlot < player.getInventory().getContainerSize(); invSlot++) {
            ItemStack stack = player.getInventory().getItem(invSlot);
            if (stack.isEmpty() || !stack.is(targetItem)) continue;
            if (isEssential(player, stack, invSlot, selectedSlot)) continue;

            int remaining = stack.getCount();

            for (int cs = 0; cs < container.getContainerSize() && remaining > 0; cs++) {
                ItemStack existing = container.getItem(cs);
                if (existing.isEmpty()) {
                    int toPlace = Math.min(remaining, container.getMaxStackSize());
                    ItemStack placed = stack.copy();
                    placed.setCount(toPlace);
                    container.setItem(cs, placed);
                    stack.shrink(toPlace);
                    remaining -= toPlace;
                    moved += toPlace;
                } else if (ItemStack.isSameItemSameComponents(existing, stack)) {
                    int canFit = Math.min(remaining, existing.getMaxStackSize() - existing.getCount());
                    if (canFit > 0) {
                        existing.grow(canFit);
                        stack.shrink(canFit);
                        remaining -= canFit;
                        moved += canFit;
                    }
                }
            }

            if (remaining > 0) break;
        }
        return moved;
    }

    private BehaviorResult tickNextItem(BotPlayer bot) {
        currentItemIdx++;
        if (currentItemIdx >= itemsToStore.size()) {
            progress.increment("items_stored", totalStored);
            progress.logEvent("Store all complete: " + totalStored + " items stored");
            bot.systemChat("Stored " + totalStored + " items total", "green");
            return BehaviorResult.SUCCESS;
        }

        candidateIdx = 0;
        phase = Phase.FIND_CONTAINER;
        return BehaviorResult.RUNNING;
    }

    private BehaviorResult tickConjuring(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        placeTicks++;

        if (placeTicks % 4 == 0) {
            var pos = net.minecraft.world.phys.Vec3.atCenterOf(placePos);
            level.sendParticles(ParticleTypes.PORTAL,
                    pos.x, pos.y + 0.5, pos.z, 3, 0.3, 0.3, 0.3, 0.1);
        }

        if (placeTicks < PLACE_TICKS) return BehaviorResult.RUNNING;

        player.giveExperienceLevels(-PLACE_XP_COST);
        level.setBlock(placePos, Blocks.CHEST.defaultBlockState(), 3);
        level.playSound(null, placePos, SoundEvents.WOOD_PLACE, SoundSource.BLOCKS, 1.0f, 1.0f);

        String dimension = level.dimension().location().toString();
        int id = ContainerRegistry.get().register(placePos, dimension, player.getName().getString());
        currentContainer = ContainerRegistry.get().get(id);

        progress.logEvent("Conjured container #" + id);
        bot.systemChat("Conjured container #" + id, "light_purple");

        player.moveTo(placePos.getX() + 0.5, placePos.getY(), placePos.getZ() + 0.5);
        phase = Phase.DEPOSITING;
        return BehaviorResult.RUNNING;
    }

    private void enterConjuring(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        placePos = player.blockPosition().relative(Direction.fromYRot(player.getYRot()), 1);
        if (!player.level().getBlockState(placePos).isAir()) {
            placePos = player.blockPosition().above();
            if (!player.level().getBlockState(placePos).isAir()) {
                placePos = player.blockPosition();
            }
        }
        if (player.experienceLevel < PLACE_XP_COST) {
            player.giveExperienceLevels(PLACE_XP_COST - player.experienceLevel);
        }
        placeTicks = 0;
        phase = Phase.CONJURING;
        progress.setPhase("conjuring container");
        bot.systemChat("No container with space — conjuring one", "light_purple");
    }

    private boolean isEssential(ServerPlayer player, ItemStack stack, int slot, int selectedSlot) {
        if (slot == selectedSlot && keepTools) return true;

        if (slot >= 36 && slot <= 39) return true;

        if (slot == 40) return true;

        if (keepFood) {
            FoodProperties food = stack.getFoodProperties(player);
            if (food != null) return true;
        }

        String itemId = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
        if (keepItems.contains(itemId)) return true;

        return false;
    }

    private boolean isStorageBlock(ServerLevel level, BlockPos pos) {
        IItemHandler handler = level.getCapability(Capabilities.ItemHandler.BLOCK, pos, null);
        if (handler != null) return true;
        BlockEntity be = level.getBlockEntity(pos);
        return be instanceof Container;
    }

    private boolean hasAnySpace(ServerLevel level, BlockPos pos) {
        IItemHandler handler = level.getCapability(Capabilities.ItemHandler.BLOCK, pos, null);
        if (handler != null) {
            for (int i = 0; i < handler.getSlots(); i++) {
                ItemStack stack = handler.getStackInSlot(i);
                if (stack.isEmpty()) return true;
                if (stack.getCount() < handler.getSlotLimit(i)) return true;
            }
            return false;
        }
        BlockEntity be = level.getBlockEntity(pos);
        if (be instanceof Container container) {
            for (int i = 0; i < container.getContainerSize(); i++) {
                ItemStack stack = container.getItem(i);
                if (stack.isEmpty()) return true;
                if (stack.getCount() < stack.getMaxStackSize()) return true;
            }
        }
        return false;
    }

    @Override
    public String describeState() {
        if (itemsToStore == null) return "Store all (scanning)";
        return "Store all (" + currentItemIdx + "/" + itemsToStore.size() + " types, " + totalStored + " stored)";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
