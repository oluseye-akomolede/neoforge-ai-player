package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.shop.BotShop;
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
import net.minecraft.world.phys.Vec3;

public class ShopBuyAction implements BotAction {
    private final String itemId;
    private final int count;
    private int ticksRemaining;
    private int totalCost;
    private String result = null;

    private static final int TICKS_PER_ITEM = 10; // half second per item

    public ShopBuyAction(String itemId, int count) {
        this.itemId = itemId;
        this.count = Math.max(1, count);
        this.ticksRemaining = -1; // set on first tick after validation
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        // First tick: validate
        if (ticksRemaining == -1) {
            BotShop.ShopItem shopItem = BotShop.get(itemId);
            if (shopItem == null) {
                result = "FAILED: '" + itemId + "' is not available in the shop. Use shop_list to see available items.";
                return true;
            }

            if (count > shopItem.maxPerPurchase()) {
                result = "FAILED: Max " + shopItem.maxPerPurchase() + " per purchase for " + itemId;
                return true;
            }

            Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
            if (item == Items.AIR) {
                result = "FAILED: Unknown item '" + itemId + "'";
                return true;
            }

            totalCost = shopItem.price() * count;

            int emeralds = countEmeralds(player);
            if (emeralds < totalCost) {
                result = "FAILED: Need " + totalCost + " emeralds but only have " + emeralds
                        + ". Use conjure to get minecraft:emerald first.";
                return true;
            }

            ticksRemaining = Math.max(20, count * TICKS_PER_ITEM);

            // Start sound
            ServerLevel level = (ServerLevel) player.level();
            level.playSound(null, player.blockPosition(),
                    SoundEvents.AMETHYST_BLOCK_CHIME, SoundSource.PLAYERS, 0.7f, 1.2f);
        }

        ServerLevel level = (ServerLevel) player.level();
        Vec3 pos = player.position();

        // Channeling particles
        if (ticksRemaining % 4 == 0) {
            level.sendParticles(ParticleTypes.HAPPY_VILLAGER,
                    pos.x, pos.y + 1.0, pos.z,
                    3, 0.6, 0.4, 0.6, 0.1);
            level.sendParticles(ParticleTypes.COMPOSTER,
                    pos.x, pos.y + 1.5, pos.z,
                    1, 0.3, 0.3, 0.3, 0.02);
        }

        ticksRemaining--;
        if (ticksRemaining > 0) return false;

        // Complete: remove emeralds, give item
        if (!removeEmeralds(player, totalCost)) {
            result = "FAILED: Lost emeralds during channeling";
            return true;
        }

        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        ItemStack stack = new ItemStack(item, count);
        player.getInventory().add(stack);

        // Completion effects
        level.sendParticles(ParticleTypes.HAPPY_VILLAGER,
                pos.x, pos.y + 1.0, pos.z,
                20, 0.8, 0.8, 0.8, 0.2);
        level.playSound(null, player.blockPosition(),
                SoundEvents.VILLAGER_YES, SoundSource.PLAYERS, 0.8f, 1.0f);

        result = "Purchased " + count + "x " + itemId + " for " + totalCost + " emeralds";
        return true;
    }

    private static int countEmeralds(ServerPlayer player) {
        int total = 0;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty() && BuiltInRegistries.ITEM.getKey(s.getItem()).toString().equals("minecraft:emerald")) {
                total += s.getCount();
            }
        }
        return total;
    }

    private static boolean removeEmeralds(ServerPlayer player, int amount) {
        int remaining = amount;
        for (int i = 0; i < player.getInventory().getContainerSize() && remaining > 0; i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty() && BuiltInRegistries.ITEM.getKey(s.getItem()).toString().equals("minecraft:emerald")) {
                int take = Math.min(s.getCount(), remaining);
                s.shrink(take);
                remaining -= take;
            }
        }
        return remaining <= 0;
    }

    @Override
    public String getResult() { return result; }

    @Override
    public String describe() {
        return String.format("ShopBuy(%s x%d, %d emeralds, %ds remaining)",
                itemId, count, totalCost, Math.max(0, ticksRemaining) / 20);
    }
}
