package com.sigmastrain.aiplayermod.brain;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.compat.bettercombat.BetterCombatCompat;
import net.minecraft.network.protocol.game.ClientboundAnimatePacket;
import net.minecraft.network.protocol.game.ClientboundHurtAnimationPacket;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.LivingEntity;

/**
 * One place that makes a bot's melee attack <em>visible</em>. A fake player
 * never goes through the client attack path, so nothing swings its arm unless
 * the server broadcasts the animation itself. Every attack site (directive
 * combat, combat-mode action, attack action) calls {@link #broadcastSwing}.
 *
 * <p>Better Combat weapons get BC's own attack animation (the packet a real
 * player's client would have sent); everything else gets the vanilla swing.
 * The vanilla swing is always sent as well — that is what a real player's
 * client does, and it keeps the swing visible for anyone whose client lacks BC.
 */
public final class AttackAnimations {

    private AttackAnimations() {}

    /** Swing the bot's main hand for everyone watching. */
    public static void broadcastSwing(ServerPlayer bot) {
        if (!(bot.level() instanceof ServerLevel sl)) return;
        try {
            BetterCombatCompat.broadcastAttackAnimation(bot);
        } catch (Exception e) {
            AIPlayerMod.LOGGER.debug("[AttackAnimations] BC compat exception, vanilla only: {}", e.getMessage());
        }
        var swing = new ClientboundAnimatePacket(bot, ClientboundAnimatePacket.SWING_MAIN_HAND);
        for (ServerPlayer online : sl.getServer().getPlayerList().getPlayers()) {
            online.connection.send(swing);
        }
    }

    /** Swing, plus the target's hurt flinch (for direct-damage paths that bypass {@code hurt}'s own broadcast). */
    public static void broadcastHit(ServerPlayer bot, LivingEntity target) {
        broadcastSwing(bot);
        if (!(bot.level() instanceof ServerLevel sl)) return;
        var hurt = new ClientboundHurtAnimationPacket(target);
        for (ServerPlayer online : sl.getServer().getPlayerList().getPlayers()) {
            online.connection.send(hurt);
        }
    }
}
