package com.sigmastrain.aiplayermod.mixin;

import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.llamalad7.mixinextras.injector.wrapoperation.WrapOperation;
import com.sigmastrain.aiplayermod.bot.BotEquipmentMenu;
import com.sigmastrain.aiplayermod.jack.JackInManager;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.ServerGamePacketListenerImpl;
import org.spongepowered.asm.mixin.Mixin;

/**
 * Jacked travelers may manage their bot's equipment.
 *
 * <p>Jack-in parks the player's body in a husk and rides the bot as a
 * SPECTATOR — and vanilla's packet handler silently discards every container
 * click a spectator sends ({@code handleContainerClick}: {@code isSpectator()
 * → sendAllDataToRemote()}), which made the bot equipment window read-only
 * exactly when it matters most (live report: "can't drag and drop while
 * jacked in"). Scoped narrowly: only while genuinely jacked, and only for
 * OUR bot menu — spectator protection for every other container stands.
 */
@Mixin(ServerGamePacketListenerImpl.class)
public class JackedContainerClickMixin {

    @WrapOperation(
            method = "handleContainerClick",
            at = @org.spongepowered.asm.mixin.injection.At(
                    value = "INVOKE",
                    target = "Lnet/minecraft/server/level/ServerPlayer;isSpectator()Z"))
    private boolean aiplayermod$allowJackedBotMenuClicks(
            ServerPlayer player, Operation<Boolean> original) {
        if (player.containerMenu instanceof BotEquipmentMenu
                && JackInManager.isJackedIn(player.getUUID())) {
            return false;
        }
        return original.call(player);
    }
}
