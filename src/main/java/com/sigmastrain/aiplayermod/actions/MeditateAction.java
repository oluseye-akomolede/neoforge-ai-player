package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.phys.Vec3;

/**
 * Meditation: bot earns XP over time by "focusing."
 * Gains 1 level per 40 ticks (2 seconds) until target is reached.
 * Emits enchanting glyphs and XP sounds while channeling.
 */
public class MeditateAction implements BotAction {
    private final int targetLevels;
    private int tickCount = 0;
    private int levelsGained = 0;
    private static final int TICKS_PER_LEVEL = 2;

    public MeditateAction(int targetLevels) {
        this.targetLevels = Math.max(1, Math.min(100, targetLevels));
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = (ServerLevel) player.level();
        Vec3 pos = player.position();
        tickCount++;

        // Emit enchanting glyphs every 4 ticks
        if (tickCount % 4 == 0) {
            level.sendParticles(ParticleTypes.ENCHANT,
                    pos.x, pos.y + 1.5, pos.z,
                    3, 0.5, 0.5, 0.5, 0.1);
        }

        if (tickCount % TICKS_PER_LEVEL == 0) {
            player.giveExperienceLevels(1);
            levelsGained++;

            // XP orb sound on each level gained
            level.playSound(null, player.blockPosition(),
                    SoundEvents.EXPERIENCE_ORB_PICKUP, SoundSource.PLAYERS,
                    0.5f, 0.8f + (levelsGained * 0.02f));

            if (levelsGained >= targetLevels) {
                // Completion burst
                level.sendParticles(ParticleTypes.ENCHANT,
                        pos.x, pos.y + 1.0, pos.z,
                        20, 1.0, 1.0, 1.0, 0.5);
                level.playSound(null, player.blockPosition(),
                        SoundEvents.PLAYER_LEVELUP, SoundSource.PLAYERS,
                        0.8f, 1.0f);
                return true;
            }
        }

        return false;
    }

    @Override
    public String describe() {
        return String.format("Meditate(target=%d, gained=%d)", targetLevels, levelsGained);
    }
}
