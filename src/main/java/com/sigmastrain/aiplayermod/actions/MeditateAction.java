package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;

/**
 * Meditation: bot earns XP over time by "focusing."
 * Gains 1 level per 40 ticks (2 seconds) until target is reached.
 */
public class MeditateAction implements BotAction {
    private final int targetLevels;
    private int tickCount = 0;
    private int levelsGained = 0;
    private static final int TICKS_PER_LEVEL = 40;

    public MeditateAction(int targetLevels) {
        this.targetLevels = Math.max(1, Math.min(100, targetLevels));
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        tickCount++;

        if (tickCount % TICKS_PER_LEVEL == 0) {
            player.giveExperienceLevels(1);
            levelsGained++;
            if (levelsGained >= targetLevels) {
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
