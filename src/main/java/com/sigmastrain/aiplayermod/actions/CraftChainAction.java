package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
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

import java.util.*;

public class CraftChainAction implements BotAction {
    private final String targetItemId;
    private final int targetCount;
    private boolean resolved = false;
    private final List<CraftStep> steps = new ArrayList<>();
    private int currentStep = 0;

    public CraftChainAction(String targetItemId, int targetCount) {
        this.targetItemId = targetItemId;
        this.targetCount = targetCount;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        var server = player.getServer();

        if (!resolved) {
            resolved = true;
            Item target;
            try { target = BuiltInRegistries.ITEM.get(ResourceLocation.parse(targetItemId)); }
            catch (Exception e) { return true; }
            if (target == null) return true;
            if (!resolveChain(target, targetCount, player, new HashSet<>())) return true;
        }

        if (currentStep >= steps.size()) return true;

        CraftStep step = steps.get(currentStep);
        boolean crafted = executeCraft(player, step.itemId, step.count);
        currentStep++;
        return currentStep >= steps.size();
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

        steps.add(new CraftStep(targetId, batches));
        return true;
    }

    private int countInInventory(ServerPlayer player, Item item) {
        int count = 0;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.getItem() == item) {
                count += stack.getCount();
            }
        }
        return count;
    }

    private boolean executeCraft(ServerPlayer player, String itemId, int batches) {
        var server = player.getServer();
        var recipeManager = server.getRecipeManager();
        Item targetItem;
        try { targetItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId)); }
        catch (Exception e) { return false; }
        if (targetItem == null) return false;

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

        for (int batch = 0; batch < batches; batch++) {
            CraftingContainer container = new TransientCraftingContainer(new AbstractContainerMenu(null, -1) {
                @Override
                public ItemStack quickMoveStack(Player p, int i) { return ItemStack.EMPTY; }
                @Override
                public boolean stillValid(Player p) { return true; }
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

            if (!hasAll) break;

            CraftingInput input = container.asCraftInput();
            Optional<RecipeHolder<CraftingRecipe>> match = recipeManager.getRecipeFor(RecipeType.CRAFTING, input, player.level());
            if (match.isEmpty()) break;

            ItemStack result = match.get().value().assemble(input, server.registryAccess());
            if (result.isEmpty()) break;

            for (int i = 0; i < ingredients.size(); i++) {
                if (!ingredients.get(i).isEmpty()) {
                    player.getInventory().getItem(usedSlots[i]).shrink(1);
                }
            }
            player.getInventory().add(result);
        }
        return true;
    }

    private record CraftStep(String itemId, int count) {}

    @Override
    public String describe() {
        return String.format("CraftChain(%s x%d, step %d/%d)", targetItemId, targetCount, currentStep, steps.size());
    }
}
