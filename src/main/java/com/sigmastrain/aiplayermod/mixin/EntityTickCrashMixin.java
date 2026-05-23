package com.sigmastrain.aiplayermod.mixin;

import com.llamalad7.mixinextras.injector.wrapmethod.WrapMethod;
import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.sigmastrain.aiplayermod.bot.BotServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.OwnableEntity;
import org.spongepowered.asm.mixin.Mixin;

import java.util.UUID;

@Mixin(value = Entity.class, priority = 100)
public class EntityTickCrashMixin {

    @WrapMethod(method = "isAlliedTo(Lnet/minecraft/world/entity/Entity;)Z")
    private boolean aiplayermod$safeIsAlliedTo(Entity other, Operation<Boolean> original) {
        Entity self = (Entity) (Object) this;

        boolean selfIsBot = self instanceof BotServerPlayer;
        boolean otherIsBot = other instanceof BotServerPlayer;

        if (!selfIsBot && !otherIsBot) {
            try {
                return original.call(other);
            } catch (NullPointerException e) {
                return false;
            }
        }

        // Bot involved — bypass vanilla team logic to prevent NPE
        if (selfIsBot && otherIsBot) return true;

        UUID botUUID = selfIsBot ? self.getUUID() : other.getUUID();
        Entity nonBot = selfIsBot ? other : self;

        if (nonBot instanceof OwnableEntity ownable) {
            UUID ownerUUID = ownable.getOwnerUUID();
            return botUUID.equals(ownerUUID);
        }
        return false;
    }
}
