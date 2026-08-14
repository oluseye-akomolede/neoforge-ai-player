package com.sigmastrain.aiplayermod.mixin;

import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.llamalad7.mixinextras.injector.wrapoperation.WrapOperation;
import net.minecraft.world.entity.ai.targeting.TargetingConditions;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;

import java.util.function.Predicate;

/**
 * Fake-player guard for mob targeting.
 *
 * <p>Our bots are {@code ServerPlayer} instances that live outside the level's
 * player list (they are packet ghosts), so they are invisible to the
 * {@code getNearbyPlayers}-style scans most mods use. But when a hostile mob
 * actually holds a bot as a target (handed to it by {@code BotAggro}), the
 * melee/combat path runs {@code TargetingConditions.test}, which invokes any
 * registered {@code selector} predicate. Some mods' selectors assume the
 * target is a fully-registered player and dereference state that fake players
 * never had (e.g. rctmod's {@code PlayerState.get(target)} returning null and
 * then calling a method on it) — an NPE that takes the whole server tick down.
 *
 * <p>Rather than disabling bot visibility outright (which made enemies ignore
 * the fleet entirely), we let the selector run but treat a crashing selector
 * as "not a valid target". This keeps targeting working for every well-behaved
 * mod while containing the one crash class that forced bots to be invisible.
 */
@Mixin(value = TargetingConditions.class, priority = 500)
public class TargetingConditionsMixin {

    @WrapOperation(
            method = "test",
            at = @At(value = "INVOKE", target = "Ljava/util/function/Predicate;test(Ljava/lang/Object;)Z")
    )
    private boolean aiplayermod$guardSelector(Predicate selector, Object target, Operation<Boolean> original) {
        try {
            return original.call(selector, target);
        } catch (RuntimeException e) {
            // A mod selector crashed on a non-standard target (our fake-player
            // bot). Report as unselectable, don't crash the tick.
            return false;
        }
    }
}
