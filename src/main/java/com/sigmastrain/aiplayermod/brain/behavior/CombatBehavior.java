package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.List;
import java.util.Random;

public class CombatBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();
    private final Random random = new Random();

    private int duration;
    private int elapsed;
    private double searchRadius;
    private boolean hostileOnly;
    private String specificTarget;

    private int attackCooldown;
    private double yVelocity;
    private boolean weaponEquipped;
    private int kills;
    private double currentSearchRadius;
    private int ticksSinceTarget;
    private Vec3 patrolDirection;
    private int patrolTicks;

    private static final double ATTACK_RANGE = 3.5;
    private static final double SPRINT_SPEED = 0.5;
    private static final double TELEPORT_THRESHOLD = 32.0;
    private static final double FLY_THRESHOLD = 4.0;
    private static final double FLY_SPEED = 0.8;
    private static final double GRAVITY = 0.08;
    private static final double JUMP_VELOCITY = 0.42;
    private static final float RETREAT_HEALTH = 4.0f;
    private static final int EAT_HUNGER_THRESHOLD = 14;
    private static final int DEFAULT_DURATION = 6000; // 5 minutes

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("combat");
        elapsed = 0;
        kills = 0;
        attackCooldown = 0;
        yVelocity = 0;
        weaponEquipped = false;

        duration = directive.getCount() > 0 ? directive.getCount() * 20 : DEFAULT_DURATION;
        searchRadius = directive.getRadius() > 0 ? directive.getRadius() : 24;
        currentSearchRadius = searchRadius;
        ticksSinceTarget = 0;
        patrolDirection = null;
        patrolTicks = 0;
        specificTarget = directive.getTarget();
        hostileOnly = specificTarget == null || specificTarget.isEmpty();

        equipBestWeapon(bot);
        weaponEquipped = true;

        String mode = specificTarget != null && !specificTarget.isEmpty()
                ? "target=" + specificTarget : "hostile mobs";
        progress.logEvent("Combat mode: " + mode + " for " + (duration / 20) + "s");
        bot.systemChat("Combat mode engaged (" + (duration / 20) + "s)", "red");
        AIPlayerMod.LOGGER.info("[{}] Combat mode: radius={}, duration={}s, target={}",
                bot.getPlayer().getName().getString(), searchRadius, duration / 20,
                specificTarget != null ? specificTarget : "hostile");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        elapsed++;

        if (elapsed >= duration) {
            progress.logEvent("Combat complete: " + kills + " kills in " + (duration / 20) + "s");
            bot.systemChat("Combat ended — " + kills + " kills", "gold");
            return BehaviorResult.SUCCESS;
        }

        if (player.getHealth() <= RETREAT_HEALTH) {
            tryEatFood(player);
            progress.logEvent("Retreating — low health");
            bot.systemChat("Retreating — low health!", "red");
            return BehaviorResult.SUCCESS;
        }

        if (player.getFoodData().getFoodLevel() < EAT_HUNGER_THRESHOLD) {
            tryEatFood(player);
        }

        if (attackCooldown > 0) attackCooldown--;

        Entity target = findTarget(player);
        if (target == null) {
            ticksSinceTarget++;
            if (ticksSinceTarget % 40 == 0 && currentSearchRadius < 256) {
                currentSearchRadius = Math.min(currentSearchRadius * 2, 256);
            }
            progress.setPhase("patrolling");
            patrol(player);
            return BehaviorResult.RUNNING;
        }

        ticksSinceTarget = 0;
        currentSearchRadius = searchRadius;
        progress.setPhase("fighting");
        bot.lookAt(target.getX(), target.getEyeY(), target.getZ());
        double dist = player.distanceTo(target);

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
                if (hpAfter <= 0) {
                    kills++;
                    progress.increment("kills");
                    progress.logEvent("Killed " + target.getName().getString());
                }
            }
        } else {
            moveToward(bot, player, target);
        }

        return BehaviorResult.RUNNING;
    }

    private Entity findTarget(ServerPlayer player) {
        AABB searchBox = player.getBoundingBox().inflate(currentSearchRadius);
        List<Entity> entities = player.level().getEntities(player, searchBox);
        Entity best = null;
        double bestDist = Double.MAX_VALUE;

        for (Entity e : entities) {
            if (!(e instanceof LivingEntity le)) continue;
            if (!le.isAlive() || le.getHealth() <= 0) continue;
            if (e instanceof ServerPlayer) continue;

            if (specificTarget != null && !specificTarget.isEmpty()) {
                String type = e.getType().toShortString().toLowerCase();
                String name = e.getName().getString().toLowerCase();
                if (!type.contains(specificTarget.toLowerCase()) && !name.contains(specificTarget.toLowerCase()))
                    continue;
            } else if (hostileOnly) {
                boolean isHostile = (e instanceof Monster) || (e instanceof Enemy)
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
                    player.getZ() + dir.z * FLY_SPEED);
            yVelocity = 0;
            return;
        }

        Vec3 dir = target.position().subtract(currentPos).normalize();
        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, dir)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }
        player.move(MoverType.SELF, new Vec3(dir.x * SPRINT_SPEED, yVelocity, dir.z * SPRINT_SPEED));
    }

    private void patrol(ServerPlayer player) {
        if (patrolDirection == null || patrolTicks <= 0) {
            double angle = random.nextDouble() * Math.PI * 2;
            patrolDirection = new Vec3(Math.cos(angle), 0, Math.sin(angle));
            patrolTicks = 60 + random.nextInt(80);
        }
        patrolTicks--;
        if (player.onGround()) {
            yVelocity = 0;
            if (com.sigmastrain.aiplayermod.actions.GoToAction.shouldJump(player, patrolDirection)) {
                yVelocity = JUMP_VELOCITY;
            }
        } else {
            yVelocity -= GRAVITY;
        }
        double walkSpeed = 0.25;
        player.move(MoverType.SELF, new Vec3(
                patrolDirection.x * walkSpeed, yVelocity, patrolDirection.z * walkSpeed));
    }

    private void equipBestWeapon(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        int bestSlot = -1;
        double bestDamage = 0;
        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            var attrs = stack.getAttributeModifiers();
            if (attrs != null) {
                for (var entry : attrs.modifiers()) {
                    if (entry.attribute().is(Attributes.ATTACK_DAMAGE)) {
                        bestDamage = Math.max(bestDamage, entry.modifier().amount());
                        if (entry.modifier().amount() >= bestDamage) bestSlot = i;
                    }
                }
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
        }
    }

    private void tryEatFood(ServerPlayer player) {
        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            FoodProperties food = stack.getFoodProperties(player);
            if (food != null) {
                player.eat(player.level(), stack);
                return;
            }
        }
    }

    private static java.lang.reflect.Field attackTickerField;
    private static boolean fieldResolved = false;

    private void forceFullAttackStrength(ServerPlayer player) {
        if (!fieldResolved) {
            fieldResolved = true;
            for (var f : LivingEntity.class.getDeclaredFields()) {
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
                                break;
                            }
                        }
                    } catch (Exception ignored) {}
                }
            }
        }
        if (attackTickerField != null) {
            try { attackTickerField.setInt(player, 100); } catch (Exception ignored) {}
        }
    }

    @Override
    public String describeState() {
        int remaining = Math.max(0, (duration - elapsed) / 20);
        return "Combat mode (" + remaining + "s left, " + kills + " kills)";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
