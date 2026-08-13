package com.sigmastrain.aiplayermod.mixin;

import com.sigmastrain.aiplayermod.client.BotSkins;
import net.minecraft.client.player.AbstractClientPlayer;
import net.minecraft.client.resources.PlayerSkin;
import net.minecraft.resources.ResourceLocation;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Client: fleet members render in fleet colors — see {@link BotSkins}. */
@Mixin(AbstractClientPlayer.class)
public abstract class BotSkinMixin {

    @Inject(method = "getSkin", at = @At("HEAD"), cancellable = true)
    private void aiplayermod$fleetSkin(CallbackInfoReturnable<PlayerSkin> cir) {
        AbstractClientPlayer self = (AbstractClientPlayer) (Object) this;
        ResourceLocation tex = BotSkins.forName(self.getGameProfile().getName());
        if (tex != null) {
            cir.setReturnValue(new PlayerSkin(tex, null, null, null,
                    PlayerSkin.Model.WIDE, true));
        }
    }
}
