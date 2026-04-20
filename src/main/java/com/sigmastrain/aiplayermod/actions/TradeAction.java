package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.npc.AbstractVillager;
import net.minecraft.world.entity.npc.Villager;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.trading.MerchantOffer;
import net.minecraft.world.item.trading.MerchantOffers;
import net.minecraft.world.phys.AABB;

import java.util.List;

/**
 * Trade with a nearby villager. Specify trade index (from list_trades)
 * and how many times to execute the trade.
 * Use trade_index = -1 to just list available trades without buying.
 */
public class TradeAction implements BotAction {
    private final int tradeIndex;
    private final int times;
    private String result = null;

    public TradeAction(int tradeIndex, int times) {
        this.tradeIndex = tradeIndex;
        this.times = Math.max(1, Math.min(16, times));
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        // Find nearest villager
        AbstractVillager villager = findNearbyVillager(player, 6.0);
        if (villager == null) {
            result = "FAILED: No villager within 6 blocks";
            return true;
        }

        MerchantOffers offers = villager.getOffers();
        if (offers.isEmpty()) {
            result = "FAILED: Villager has no trades available";
            return true;
        }

        // List mode
        if (tradeIndex < 0) {
            StringBuilder sb = new StringBuilder("Available trades:\n");
            for (int i = 0; i < offers.size(); i++) {
                MerchantOffer offer = offers.get(i);
                String costA = formatStack(offer.getCostA());
                String costB = offer.getCostB().isEmpty() ? "" : " + " + formatStack(offer.getCostB());
                String output = formatStack(offer.getResult());
                int uses = offer.getMaxUses() - offer.getUses();
                sb.append(String.format("  [%d] %s%s -> %s (stock: %d)\n", i, costA, costB, output, uses));
            }
            result = sb.toString();
            return true;
        }

        if (tradeIndex >= offers.size()) {
            result = "FAILED: Trade index " + tradeIndex + " out of range (max " + (offers.size() - 1) + ")";
            return true;
        }

        MerchantOffer offer = offers.get(tradeIndex);
        int successCount = 0;

        for (int t = 0; t < times; t++) {
            if (offer.isOutOfStock()) break;

            // Check if player has the required items
            ItemStack costA = offer.getCostA().copy();
            ItemStack costB = offer.getCostB().copy();

            if (!consumeFromInventory(player, costA)) break;
            if (!costB.isEmpty() && !consumeFromInventory(player, costB)) {
                // Return costA since we already took it
                player.getInventory().add(costA);
                break;
            }

            // Execute trade
            ItemStack tradeResult = offer.getResult().copy();
            player.getInventory().add(tradeResult);
            offer.increaseUses();

            // Award villager trading XP
            villager.notifyTrade(offer);

            successCount++;
        }

        if (successCount == 0) {
            result = "FAILED: Cannot afford trade (need " + formatStack(offer.getCostA()) + ")";
        } else {
            result = "Traded " + successCount + "x: " + formatStack(offer.getCostA())
                    + " -> " + formatStack(offer.getResult());
        }

        return true;
    }

    private boolean consumeFromInventory(ServerPlayer player, ItemStack required) {
        int needed = required.getCount();
        var inv = player.getInventory();
        for (int i = 0; i < inv.getContainerSize() && needed > 0; i++) {
            ItemStack slot = inv.getItem(i);
            if (ItemStack.isSameItemSameComponents(slot, required)) {
                int take = Math.min(needed, slot.getCount());
                slot.shrink(take);
                needed -= take;
            }
        }
        return needed <= 0;
    }

    private AbstractVillager findNearbyVillager(ServerPlayer player, double radius) {
        AABB box = player.getBoundingBox().inflate(radius);
        List<AbstractVillager> villagers = player.level().getEntitiesOfClass(
                AbstractVillager.class, box);
        if (villagers.isEmpty()) return null;
        // Return closest
        villagers.sort((a, b) -> Double.compare(a.distanceTo(player), b.distanceTo(player)));
        return villagers.get(0);
    }

    private String formatStack(ItemStack stack) {
        if (stack.isEmpty()) return "nothing";
        String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
        return stack.getCount() + "x " + id;
    }

    @Override
    public String getResult() { return result; }

    @Override
    public String describe() {
        if (tradeIndex < 0) return "Trade(listing)";
        return String.format("Trade(index=%d, times=%d)", tradeIndex, times);
    }
}
