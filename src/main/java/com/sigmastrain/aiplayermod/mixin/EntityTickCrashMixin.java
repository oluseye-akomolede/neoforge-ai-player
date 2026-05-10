package com.sigmastrain.aiplayermod.mixin;

import com.llamalad7.mixinextras.injector.wrapmethod.WrapMethod;
import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.sigmastrain.aiplayermod.bot.BotServerPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.OwnableEntity;
import org.spongepowered.asm.mixin.Mixin;

import java.lang.reflect.Method;
import java.util.UUID;

@Mixin(value = Entity.class, priority = 100)
public class EntityTickCrashMixin {

    @WrapMethod(method = "isAlliedTo(Lnet/minecraft/world/entity/Entity;)Z")
    private boolean aiplayermod$safeIsAlliedTo(Entity other, Operation<Boolean> original) {
        Entity self = (Entity) (Object) this;

        if (isBotRelated(self) || isBotRelated(other)) {
            UUID selfOwner = getOwnerUUID(self);
            UUID otherOwner = getOwnerUUID(other);
            return selfOwner != null && selfOwner.equals(otherOwner);
        }

        try {
            return original.call(other);
        } catch (NullPointerException e) {
            return false;
        }
    }

    private static boolean isBotRelated(Entity entity) {
        if (entity instanceof BotServerPlayer) return true;

        if (entity instanceof ServerPlayer sp) {
            for (var bot : com.sigmastrain.aiplayermod.bot.BotManager.getAllBots().values()) {
                if (bot.getPlayer().getUUID().equals(sp.getUUID())) return true;
            }
        }

        UUID owner = getOwnerUUID(entity);
        if (owner == null) return false;
        for (var bot : com.sigmastrain.aiplayermod.bot.BotManager.getAllBots().values()) {
            if (bot.getPlayer().getUUID().equals(owner)) return true;
        }
        return false;
    }

    private static UUID getOwnerUUID(Entity entity) {
        if (entity instanceof OwnableEntity ownable) {
            return ownable.getOwnerUUID();
        }
        // Ars Nouveau summons (ISummon interface) — use reflection to avoid hard dep
        try {
            Method m = entity.getClass().getMethod("getOwnerID");
            Object result = m.invoke(entity);
            if (result instanceof UUID uuid) return uuid;
        } catch (Exception ignored) {
        }
        try {
            var data = entity.getPersistentData();
            if (data.contains("Owner")) {
                return data.getUUID("Owner");
            }
        } catch (Exception ignored) {
        }
        return null;
    }
}
