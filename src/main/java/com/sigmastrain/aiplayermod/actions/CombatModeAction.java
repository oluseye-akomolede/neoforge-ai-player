package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
import net.minecraft.core.registries.BuiltInRegistries;

import java.util.List;

public class CombatModeAction implements BotAction {
    private final double searchRadius;
    private final boolean hostileOnly;
    private final String specificTarget;
    private int ticksWithoutTarget = 0;
    private int attackCooldown = 0;
    private double yVelocity = 0;
    private boolean weaponEquipped = false;
    private boolean initialized = false;

    private static final double ATTACK_RANGE = 3.5;
    private static final double SPRINT_SPEED = 0.5;
    private static final double FLY_SPEED = 0.8;
    private static final double TELEPORT_THRESHOLD = 32.0;
    private static final double FLY_THRESHOLD = 4.0;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final int IDLE_TIMEOUT = 100; // 5 seconds with no target
    private static final int EAT_HUNGER_THRESHOLD = 14;
    private static final float RETREAT_HEALTH = 4.0f;

    public CombatModeAction(double searchRadius, boolean hostileOnly, String specificTarget) {
        this.searchRadius = Math.max(searchRadius, 16.0);
        this.hostileOnly = hostileOnly;
        this.specificTarget = specificTarget != null ? specificTarget.toLowerCase() : null;
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (!initialized) {
            initialized = true;
            bot.drainChatInbox();
            AIPlayerMod.LOGGER.info("Bot {} entered combat mode (radius={}, hostileOnly={})",
                    player.getName().getString(), searchRadius, hostileOnly);
        }

        if (bot.hasPendingChat()) {
            AIPlayerMod.LOGGER.info("Bot {} exiting combat mode: chat interrupt",
                    player.getName().getString());
            return true;
        }

        if (player.getHealth() <= RETREAT_HEALTH) {
            tryEatFood(player);
            return true;
        }

        if (player.getFoodData().getFoodLevel() < EAT_HUNGER_THRESHOLD) {
            tryEatFood(player);
        }

        if (!weaponEquipped) {
            equipBestWeapon(bot);
            weaponEquipped = true;
        }

        if (attackCooldown > 0) {
            attackCooldown--;
        }

        Entity target = findTarget(player);

        if (target == null) {
            ticksWithoutTarget++;
            if (!player.onGround()) {
                yVelocity -= GRAVITY;
                player.move(MoverType.SELF, new Vec3(0, yVelocity, 0));
            }
            return ticksWithoutTarget > IDLE_TIMEOUT;
        }

        ticksWithoutTarget = 0;
        double dist = player.distanceTo(target);

        bot.lookAt(target.getX(), target.getEyeY(), target.getZ());

        if (dist <= ATTACK_RANGE) {
            if (attackCooldown <= 0) {
                float hpBefore = target instanceof LivingEntity lt ? lt.getHealth() : -1;
                forceFullAttackStrength(player);
                player.attack(target);
                player.resetAttackStrengthTicker();
                float hpAfter = target instanceof LivingEntity lt2 ? lt2.getHealth() : -1;
                boolean didDamage = hpAfter < hpBefore;
                if (!didDamage && target instanceof LivingEntity lt3) {
                    float weaponDamage = (float) player.getAttributeValue(Attributes.ATTACK_DAMAGE);
                    lt3.hurt(player.damageSources().playerAttack(player), weaponDamage);
                    hpAfter = lt3.getHealth();
                }
                attackCooldown = 15;
                AIPlayerMod.LOGGER.info("Bot {} attacked {} (dist={}, hp={}->{}, dmg={})",
                        player.getName().getString(),
                        target.getName().getString(),
                        String.format("%.1f", dist),
                        String.format("%.1f", hpBefore),
                        String.format("%.1f", hpAfter),
                        didDamage ? "player.attack" : "direct.hurt");
            }
        } else {
            moveToward(bot, player, target);
        }

        return false;
    }

    private Entity findTarget(ServerPlayer player) {
        AABB searchBox = player.getBoundingBox().inflate(searchRadius);
        List<Entity> entities = player.level().getEntities(player, searchBox);

        Entity best = null;
        double bestDist = Double.MAX_VALUE;

        for (Entity e : entities) {
            if (!(e instanceof LivingEntity le)) continue;
            if (!le.isAlive()) continue;
            if (le.getHealth() <= 0) continue;
            if (e instanceof ServerPlayer) continue;

            if (specificTarget != null) {
                String type = e.getType().toShortString().toLowerCase();
                String name = e.getName().getString().toLowerCase();
                if (!type.contains(specificTarget) && !name.contains(specificTarget)) continue;
            } else if (hostileOnly) {
                boolean isHostile = (e instanceof Monster)
                        || (e instanceof Enemy)
                        || e.getType().getCategory() == MobCategory.MONSTER;
                if (!isHostile) continue;
            }

            double dist = e.distanceTo(player);
            if (dist < bestDist) {
                bestDist = dist;
                best = e;
            }
        }
        return best;
    }

    private void moveToward(BotPlayer bot, ServerPlayer player, Entity target) {
        Vec3 currentPos = player.position();
        double dist = player.distanceTo(target);
        double heightDiff = Math.abs(target.getY() - player.getY());

        if (dist > TELEPORT_THRESHOLD) {
            Vec3 tPos = target.position();
            Vec3 dir = currentPos.subtract(tPos).normalize();
            player.moveTo(tPos.x + dir.x * ATTACK_RANGE, tPos.y, tPos.z + dir.z * ATTACK_RANGE);
            yVelocity = 0;
            return;
        }

        if (heightDiff > FLY_THRESHOLD || (!player.onGround() && heightDiff > 1.5)) {
            Vec3 dir = target.position().subtract(currentPos).normalize();
            player.moveTo(
                    player.getX() + dir.x * FLY_SPEED,
                    player.getY() + dir.y * FLY_SPEED,
                    player.getZ() + dir.z * FLY_SPEED
            );
            yVelocity = 0;
            return;
        }

        Vec3 dir = target.position().subtract(currentPos).normalize();

        if (player.onGround()) {
            yVelocity = 0;
            if (GoToAction.shouldJump(player, dir)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }

        player.move(MoverType.SELF, new Vec3(dir.x * SPRINT_SPEED, yVelocity, dir.z * SPRINT_SPEED));
    }

    private void equipBestWeapon(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        int bestSlot = -1;
        double bestDamage = 0;

        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;

            double damage = 0;
            var attrs = stack.getAttributeModifiers();
            if (attrs != null) {
                for (var entry : attrs.modifiers()) {
                    if (entry.attribute().is(Attributes.ATTACK_DAMAGE)) {
                        damage = Math.max(damage, entry.modifier().amount());
                    }
                }
            }

            if (damage > bestDamage) {
                bestDamage = damage;
                bestSlot = i;
            }
        }

        if (bestSlot >= 0) {
            if (bestSlot < 9) {
                player.getInventory().selected = bestSlot;
            } else {
                ItemStack weapon = player.getInventory().getItem(bestSlot);
                ItemStack existing = player.getInventory().getItem(0);
                player.getInventory().setItem(0, weapon.copy());
                player.getInventory().setItem(bestSlot, existing);
                player.getInventory().selected = 0;
            }
            bot.broadcastEquipmentChange(EquipmentSlot.MAINHAND,
                    player.getInventory().getItem(player.getInventory().selected));
            String itemId = BuiltInRegistries.ITEM.getKey(
                    player.getInventory().getItem(player.getInventory().selected).getItem()).toString();
            AIPlayerMod.LOGGER.info("Bot {} equipped weapon: {}", player.getName().getString(), itemId);
        }
    }

    private void tryEatFood(ServerPlayer player) {
        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            FoodProperties food = stack.getFoodProperties(player);
            if (food != null) {
                player.eat(player.level(), stack);
                AIPlayerMod.LOGGER.info("Bot {} ate food from slot {}", player.getName().getString(), i);
                return;
            }
        }
    }

    private static java.lang.reflect.Field attackTickerField;
    private static boolean fieldResolved = false;

    private void forceFullAttackStrength(ServerPlayer player) {
        if (!fieldResolved) {
            fieldResolved = true;
            for (var f : net.minecraft.world.entity.LivingEntity.class.getDeclaredFields()) {
                if (f.getType() == int.class) {
                    f.setAccessible(true);
                    try {
                        int val = f.getInt(player);
                        if (val >= 0 && val < 1000) {
                            f.setInt(player, 100);
                            float scale = player.getAttackStrengthScale(0.5f);
                            f.setInt(player, val);
                            if (scale >= 0.9f) {
                                attackTickerField = f;
                                AIPlayerMod.LOGGER.info("Found attack ticker field: {}", f.getName());
                                break;
                            }
                        }
                    } catch (Exception ignored) {}
                }
            }
            if (attackTickerField == null) {
                AIPlayerMod.LOGGER.warn("Could not find attackStrengthTicker field!");
            }
        }
        if (attackTickerField != null) {
            try {
                attackTickerField.setInt(player, 100);
            } catch (Exception ignored) {}
        }
    }

    @Override
    public String describe() {
        if (specificTarget != null) return "CombatMode(target=" + specificTarget + ")";
        return "CombatMode(" + (hostileOnly ? "hostile" : "all") + ")";
    }
}
