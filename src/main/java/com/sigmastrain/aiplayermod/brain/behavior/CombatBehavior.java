package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.bettercombat.BetterCombatCompat;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.TicketType;
import net.minecraft.world.level.ChunkPos;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.entity.MobSpawnType;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.entity.projectile.AbstractArrow;
import net.minecraft.network.protocol.game.ClientboundAnimatePacket;
import net.minecraft.network.protocol.game.ClientboundHurtAnimationPacket;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.BowItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.enchantment.EnchantmentHelper;
import net.minecraft.world.level.levelgen.Heightmap;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.ArrayList;
import java.util.Comparator;
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
    private boolean weaponEquipped;
    private int kills;
    private int patrolCooldown;
    private int spawnCooldown;
    private int noTargetTicks;

    private static final TicketType<ChunkPos> BOT_TICKET =
            TicketType.create("aiplayermod_bot", Comparator.comparingLong(ChunkPos::toLong), 200);

    private static final double MELEE_RANGE = 2.5;
    private static final double PATROL_RADIUS = 80.0;
    private static final int PATROL_INTERVAL = 60;
    private static final float RETREAT_HEALTH = 4.0f;
    private static final int EAT_HUNGER_THRESHOLD = 14;
    private static final int DEFAULT_DURATION = 6000;
    private static final int SPAWN_COOLDOWN_TICKS = 200;
    private static final int NO_TARGET_THRESHOLD = 100;
    private static final int MOBS_PER_WAVE = 3;

    @SuppressWarnings("unchecked")
    private static final EntityType<? extends Monster>[] HOSTILE_TYPES = new EntityType[]{
            EntityType.ZOMBIE, EntityType.SKELETON, EntityType.SPIDER, EntityType.CREEPER
    };

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("combat");
        elapsed = 0;
        kills = 0;
        attackCooldown = 0;
        weaponEquipped = false;
        patrolCooldown = 0;
        spawnCooldown = 0;
        noTargetTicks = 0;

        duration = directive.getCount() > 0 ? directive.getCount() * 20 : DEFAULT_DURATION;
        searchRadius = directive.getRadius() > 0 ? directive.getRadius() : 256;
        specificTarget = directive.getTarget();
        hostileOnly = specificTarget == null || specificTarget.isEmpty();

        equipBestWeapon(bot);
        weaponEquipped = true;

        // Ensure entity-ticking around bot's starting position
        ServerPlayer player = bot.getPlayer();
        if (player.level() instanceof ServerLevel serverLevel) {
            ChunkPos center = new ChunkPos(player.blockPosition());
            serverLevel.getChunkSource().addRegionTicket(BOT_TICKET, center, 3, center);
        }

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
            boolean ate = tryEatFood(player);
            if (!ate) {
                progress.logEvent("Retreating — low health, no food");
                bot.systemChat("Retreating — no food!", "red");
                return BehaviorResult.SUCCESS;
            }
            progress.logEvent("Ate food at low health");
        }

        if (player.getFoodData().getFoodLevel() < EAT_HUNGER_THRESHOLD) {
            tryEatFood(player);
        }

        if (attackCooldown > 0) attackCooldown--;
        if (spawnCooldown > 0) spawnCooldown--;

        Entity target = findTarget(player);

        if (target == null) {
            noTargetTicks++;
            if (hostileOnly && noTargetTicks >= NO_TARGET_THRESHOLD && spawnCooldown <= 0) {
                spawnHostileMobs(player);
                spawnCooldown = SPAWN_COOLDOWN_TICKS;
                noTargetTicks = 0;
            }
            progress.setPhase("patrolling");
            patrol(player);
            return BehaviorResult.RUNNING;
        }
        noTargetTicks = 0;

        progress.setPhase("fighting");
        bot.lookAt(target.getX(), target.getEyeY(), target.getZ());

        double dist = player.distanceTo(target);

        // Always teleport to melee range if not already there
        if (dist > MELEE_RANGE) {
            // Bonus: shoot arrow first if we have a bow
            if (dist > 8.0) {
                tryBowShot(bot, player, target);
            }
            teleportToTarget(player, target);
            dist = player.distanceTo(target);
        }

        // Direct damage — bypasses player attack system which doesn't work for fake players
        if (dist <= MELEE_RANGE && attackCooldown <= 0 && target instanceof LivingEntity le) {
            le.invulnerableTime = 0;
            ItemStack weapon = player.getInventory().getItem(player.getInventory().selected);
            float baseDamage = getHeldWeaponDamage(player);
            DamageSource damageSource = player.damageSources().playerAttack(player);

            // Apply enchantment damage bonus (Sharpness, Smite, Bane of Arthropods, etc.)
            float damage = baseDamage;
            if (player.level() instanceof ServerLevel sl && !weapon.isEmpty()) {
                damage = EnchantmentHelper.modifyDamage(sl, weapon, le, damageSource, baseDamage);
            }

            boolean hurt = le.hurt(damageSource, damage);

            // Apply enchantment post-attack effects (Fire Aspect, Knockback, etc.)
            if (hurt && player.level() instanceof ServerLevel sl && !weapon.isEmpty()) {
                EnchantmentHelper.doPostAttackEffectsWithItemSource(sl, le, damageSource, weapon);
            }

            // Broadcast attack animation — use Better Combat if available, vanilla swing otherwise
            if (player.level() instanceof ServerLevel sl) {
                boolean bcHandled = false;
                try {
                    bcHandled = BetterCombatCompat.broadcastAttackAnimation(player);
                } catch (Exception e) {
                    AIPlayerMod.LOGGER.debug("[CombatBehavior] BC compat exception, using vanilla: {}", e.getMessage());
                }
                if (!bcHandled) {
                    var swingPacket = new ClientboundAnimatePacket(player, ClientboundAnimatePacket.SWING_MAIN_HAND);
                    for (ServerPlayer online : sl.getServer().getPlayerList().getPlayers()) {
                        online.connection.send(swingPacket);
                    }
                }
                var hurtPacket = new ClientboundHurtAnimationPacket(le);
                for (ServerPlayer online : sl.getServer().getPlayerList().getPlayers()) {
                    online.connection.send(hurtPacket);
                }
            }

            AIPlayerMod.LOGGER.info("[{}] Attack {} — dmg={} (base={}), hurt={}, hp={}/{}",
                    player.getName().getString(), target.getName().getString(),
                    damage, baseDamage, hurt, le.getHealth(), le.getMaxHealth());

            String targetName = target.getName().getString();
            String dmgStr = String.format("%.1f", damage);
            String hpStr = String.format("%.0f/%.0f", le.getHealth(), le.getMaxHealth());
            String bonusInfo = damage > baseDamage
                    ? String.format(" (+%.1f enchant)", damage - baseDamage)
                    : "";
            bot.systemChat("Hit " + targetName + " for " + dmgStr + bonusInfo +
                    " — " + hpStr + " HP left", "yellow");
            progress.logEvent("Hit " + targetName + " for " + dmgStr + bonusInfo);

            if (!hurt) {
                le.setHealth(le.getHealth() - damage);
            }

            attackCooldown = 10;

            if (!le.isAlive() || le.getHealth() <= 0) {
                if (le.isAlive()) le.kill();
                kills++;
                progress.increment("kills");
                progress.logEvent("Killed " + targetName + " (" + kills + " total)");
                bot.systemChat("Killed " + targetName + "! (" + kills + " kills)", "green");
                teleportBot(player, target.getX(), target.getY(), target.getZ());
                collectNearbyItems(player);
            }
        }

        if (elapsed % 20 == 0) collectNearbyItems(player);

        return BehaviorResult.RUNNING;
    }

    private Entity findTarget(ServerPlayer player) {
        if (!(player.level() instanceof ServerLevel serverLevel)) return null;

        // Use getAllEntities() — AABB search relies on entity sections which aren't active for fake players
        Entity best = null;
        double bestDist = Double.MAX_VALUE;
        double searchRadiusSq = searchRadius * searchRadius;
        int totalScanned = 0;
        int matchedType = 0;

        for (Entity e : serverLevel.getAllEntities()) {
            if (!(e instanceof LivingEntity le)) continue;
            if (!le.isAlive() || le.getHealth() <= 0) continue;
            if (e instanceof ServerPlayer) continue;

            double distSq = e.distanceToSqr(player);
            if (distSq > searchRadiusSq) continue;
            totalScanned++;

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

            matchedType++;
            if (distSq < bestDist) {
                bestDist = distSq;
                best = e;
            }
        }

        if (elapsed % 100 == 0) {
            AIPlayerMod.LOGGER.info("[{}] findTarget: scanned={} matched={} best={}",
                    player.getName().getString(), totalScanned, matchedType,
                    best != null ? best.getName().getString() + " @" + String.format("%.0f", Math.sqrt(bestDist)) : "none");
        }

        return best;
    }

    private void teleportToTarget(ServerPlayer player, Entity target) {
        Vec3 tPos = target.position();
        Vec3 dir = player.position().subtract(tPos);
        double len = dir.length();
        if (len > 0.1) {
            dir = dir.normalize();
        } else {
            dir = new Vec3(1, 0, 0);
        }
        teleportBot(player, tPos.x + dir.x * MELEE_RANGE * 0.8, tPos.y, tPos.z + dir.z * MELEE_RANGE * 0.8);
    }

    private void patrol(ServerPlayer player) {
        if (patrolCooldown > 0) {
            patrolCooldown--;
            return;
        }
        patrolCooldown = PATROL_INTERVAL;

        double angle = random.nextDouble() * Math.PI * 2;
        double radius = PATROL_RADIUS * (0.3 + random.nextDouble() * 0.7);
        double tx = player.getX() + Math.cos(angle) * radius;
        double tz = player.getZ() + Math.sin(angle) * radius;
        int surfaceY = player.level().getHeight(Heightmap.Types.MOTION_BLOCKING, (int) tx, (int) tz);
        teleportBot(player, tx, surfaceY + 1, tz);
    }

    private void teleportBot(ServerPlayer player, double x, double y, double z) {
        player.moveTo(x, y, z);
        if (player.level() instanceof ServerLevel serverLevel) {
            ChunkPos center = new ChunkPos(player.blockPosition());
            // Entity-ticking ticket — makes entities in nearby chunks visible and active
            serverLevel.getChunkSource().addRegionTicket(BOT_TICKET, center, 3, center);
        }
    }

    private void tryBowShot(BotPlayer bot, ServerPlayer player, Entity target) {
        int bowSlot = findBow(player);
        if (bowSlot < 0) return;
        if (!hasArrows(player)) return;

        int prevSlot = player.getInventory().selected;
        if (bowSlot < 9) {
            player.getInventory().selected = bowSlot;
        } else {
            ItemStack bow = player.getInventory().getItem(bowSlot);
            ItemStack existing = player.getInventory().getItem(0);
            player.getInventory().setItem(0, bow.copy());
            player.getInventory().setItem(bowSlot, existing);
            player.getInventory().selected = 0;
        }

        Vec3 toTarget = target.position().add(0, target.getBbHeight() * 0.6, 0).subtract(player.getEyePosition());
        float velocity = 3.0f;
        ItemStack arrowStack = new ItemStack(Items.ARROW);
        AbstractArrow arrow = new net.minecraft.world.entity.projectile.Arrow(
                player.level(), player, arrowStack, null);
        arrow.shoot(toTarget.x, toTarget.y, toTarget.z, velocity, 1.0f);
        arrow.setCritArrow(true);
        player.level().addFreshEntity(arrow);

        consumeArrow(player);

        // Restore weapon
        player.getInventory().selected = prevSlot;
        bot.broadcastEquipmentChange(EquipmentSlot.MAINHAND,
                player.getInventory().getItem(player.getInventory().selected));
    }

    private int findBow(ServerPlayer player) {
        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty() && stack.getItem() instanceof BowItem) return i;
        }
        return -1;
    }

    private boolean hasArrows(ServerPlayer player) {
        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty() && stack.is(Items.ARROW)) return true;
        }
        return false;
    }

    private void consumeArrow(ServerPlayer player) {
        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty() && stack.is(Items.ARROW)) {
                stack.shrink(1);
                return;
            }
        }
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
                        if (entry.modifier().amount() >= bestDamage) {
                            bestDamage = entry.modifier().amount();
                            bestSlot = i;
                        }
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

    private float getHeldWeaponDamage(ServerPlayer player) {
        ItemStack held = player.getInventory().getItem(player.getInventory().selected);
        double weaponBonus = 0;
        if (!held.isEmpty()) {
            var attrs = held.getAttributeModifiers();
            if (attrs != null) {
                for (var entry : attrs.modifiers()) {
                    if (entry.attribute().is(Attributes.ATTACK_DAMAGE)) {
                        weaponBonus = Math.max(weaponBonus, entry.modifier().amount());
                    }
                }
            }
        }
        // 1.0 base player damage + weapon bonus, minimum 2.0
        return Math.max((float) (1.0 + weaponBonus), 2.0f);
    }

    private void collectNearbyItems(ServerPlayer player) {
        if (!(player.level() instanceof ServerLevel serverLevel)) return;
        double pickupRadiusSq = 10.0 * 10.0;
        for (Entity e : serverLevel.getAllEntities()) {
            if (!(e instanceof ItemEntity ie)) continue;
            if (!ie.isAlive()) continue;
            if (ie.distanceToSqr(player) > pickupRadiusSq) continue;
            ItemStack stack = ie.getItem().copy();
            if (player.getInventory().add(stack)) {
                ie.discard();
            }
        }
    }

    private void spawnHostileMobs(ServerPlayer player) {
        if (!(player.level() instanceof ServerLevel serverLevel)) return;
        int spawned = 0;
        for (int i = 0; i < MOBS_PER_WAVE; i++) {
            EntityType<? extends Monster> type = HOSTILE_TYPES[random.nextInt(HOSTILE_TYPES.length)];
            double angle = random.nextDouble() * Math.PI * 2;
            double dist = 10 + random.nextDouble() * 20;
            double sx = player.getX() + Math.cos(angle) * dist;
            double sz = player.getZ() + Math.sin(angle) * dist;
            int sy = serverLevel.getHeight(Heightmap.Types.MOTION_BLOCKING, (int) sx, (int) sz);
            Monster mob = type.create(serverLevel);
            if (mob == null) continue;
            mob.moveTo(sx, sy, sz, random.nextFloat() * 360, 0);
            mob.finalizeSpawn(serverLevel, serverLevel.getCurrentDifficultyAt(mob.blockPosition()),
                    MobSpawnType.MOB_SUMMONED, null);
            serverLevel.addFreshEntityWithPassengers(mob);
            spawned++;
        }
        if (spawned > 0) {
            AIPlayerMod.LOGGER.info("[{}] Spawned {} hostile mobs (no targets found for {}t)",
                    player.getName().getString(), spawned, NO_TARGET_THRESHOLD);
            progress.logEvent("Spawned " + spawned + " hostile mobs");
        }
    }

    private boolean tryEatFood(ServerPlayer player) {
        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;
            FoodProperties food = stack.getFoodProperties(player);
            if (food != null) {
                player.eat(player.level(), stack);
                player.setHealth(Math.min(player.getHealth() + food.nutrition() * 0.5f, player.getMaxHealth()));
                return true;
            }
        }
        return false;
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
