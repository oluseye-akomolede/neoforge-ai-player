package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.CraftingContainer;
import net.minecraft.world.inventory.TransientCraftingContainer;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.*;

import java.util.Optional;

public class CraftAction implements BotAction {
    private final String itemId;
    private final int count;

    public CraftAction(String itemId, int count) {
        this.itemId = itemId;
        this.count = count;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        var server = player.getServer();
        var recipeManager = server.getRecipeManager();

        Item targetItem;
        try {
            targetItem = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        } catch (Exception e) { return true; }
        if (targetItem == null) return true;

        var allRecipes = recipeManager.getAllRecipesFor(RecipeType.CRAFTING);

        RecipeHolder<CraftingRecipe> matchedRecipe = null;
        for (var holder : allRecipes) {
            ItemStack result = holder.value().getResultItem(server.registryAccess());
            if (result.getItem() == targetItem) {
                matchedRecipe = holder;
                break;
            }
        }

        if (matchedRecipe == null) return true;

        int crafted = 0;
        while (crafted < count) {
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
                if (!found) {
                    hasAll = false;
                    break;
                }
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
            crafted += result.getCount();
        }

        return true;
    }

    @Override
    public String describe() {
        return String.format("Craft(%s x%d)", itemId, count);
    }
}
