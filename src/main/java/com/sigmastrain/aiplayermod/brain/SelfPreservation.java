package com.sigmastrain.aiplayermod.brain;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

public class SelfPreservation {
    private static final float CRITICAL_HEALTH = 4.0f;
    private static final int HUNGER_THRESHOLD = 14;
    private static final double FLEE_DISTANCE = 16.0;
    private static final int EAT_COOLDOWN_TICKS = 40;

    private int eatCooldown = 0;
    private boolean fleeing = false;

    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        if (eatCooldown > 0) eatCooldown--;

        if (shouldFlee(player)) {
            flee(bot, player);
            return true;
        }
        fleeing = false;

        if (shouldEat(player)) {
            eat(bot, player);
            return true;
        }

        return false;
    }

    public boolean isFleeing() {
        return fleeing;
    }

    private boolean shouldFlee(ServerPlayer player) {
        if (player.getHealth() > CRITICAL_HEALTH) return false;
        AABB box = player.getBoundingBox().inflate(8.0);
        for (Entity e : player.level().getEntities(player, box)) {
            if (e instanceof Enemy) return true;
        }
        return false;
    }

    private void flee(BotPlayer bot, ServerPlayer player) {
        fleeing = true;
        Vec3 fleeDir = Vec3.ZERO;
        AABB box = player.getBoundingBox().inflate(12.0);
        int count = 0;
        for (Entity e : player.level().getEntities(player, box)) {
            if (e instanceof Enemy) {
                Vec3 away = player.position().subtract(e.position()).normalize();
                fleeDir = fleeDir.add(away);
                count++;
            }
        }
        if (count == 0) return;
        fleeDir = fleeDir.normalize();

        double speed = 0.4;
        double yVel = 0;
        if (player.onGround()) {
            Vec3 dir = fleeDir;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, dir)) {
                yVel = 0.42;
            }
        }
        player.move(MoverType.SELF, new Vec3(fleeDir.x * speed, yVel, fleeDir.z * speed));

        if (shouldEat(player) && eatCooldown <= 0) {
            eat(bot, player);
        }
    }

    private boolean shouldEat(ServerPlayer player) {
        return player.getFoodData().getFoodLevel() < HUNGER_THRESHOLD
                || player.getHealth() < player.getMaxHealth() - 2;
    }

    private void eat(BotPlayer bot, ServerPlayer player) {
        if (eatCooldown > 0) return;

        int bestSlot = -1;
        int bestNutrition = 0;
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            FoodProperties food = stack.getItem().getFoodProperties(stack, player);
            if (food != null && food.nutrition() > bestNutrition) {
                bestNutrition = food.nutrition();
                bestSlot = i;
            }
        }

        if (bestSlot >= 0) {
            ItemStack food = player.getInventory().getItem(bestSlot);
            player.getFoodData().eat(food.getItem().getFoodProperties(food, player));
            food.shrink(1);
            eatCooldown = EAT_COOLDOWN_TICKS;
        }
    }
}
