package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.*;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.phys.Vec3;

/**
 * Standalone meditation — the XP-earning half of {@link ChannelBehavior}'s
 * MEDITATING phase, promoted to a directive of its own. Bots have no other
 * income; without this, a broke bot (Tiller, 0 levels, anchor refused) has
 * no way back into the economy except being handed a conjure order.
 *
 * <p>count = XP levels to gain (default 10). Same ×10-per-tick grant as
 * ritual meditation, but pacing here is one grant per second so the player
 * can watch the level counter climb instead of it snapping instantly.
 */
public class MeditateBehavior implements Behavior {

    private static final int DEFAULT_LEVELS = 10;
    private static final int MAX_LEVELS = 100;
    private static final int TICKS_PER_GRANT = 20;
    private static final int LEVELS_PER_GRANT = 10;

    private final ProgressReport progress = new ProgressReport();
    private int target;
    private int gained;
    private int ticks;
    private boolean done;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        gained = 0;
        ticks = 0;
        done = false;
        int c = directive.getCount();
        target = c > 0 ? Math.min(c, MAX_LEVELS) : DEFAULT_LEVELS;
        progress.setPhase("MEDITATING");
        progress.logEvent("Meditating for " + target + " XP levels");
        bot.systemChat("Meditating for " + target + " XP levels...", "light_purple");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (done) return BehaviorResult.SUCCESS;
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        ticks++;

        if (ticks % 4 == 0) {
            Vec3 pos = player.position();
            level.sendParticles(ParticleTypes.ENCHANT,
                    pos.x, pos.y + 1.5, pos.z, 3, 0.5, 0.5, 0.5, 0.1);
        }

        if (ticks % TICKS_PER_GRANT == 0) {
            int grant = Math.min(LEVELS_PER_GRANT, target - gained);
            player.giveExperienceLevels(grant);
            gained += grant;
            progress.increment("xp_levels_gained");

            if (gained >= target) {
                done = true;
                progress.logEvent("Meditation complete: gained " + gained
                        + " levels (now L" + player.experienceLevel + ")");
                progress.putResult("levels_gained", String.valueOf(gained));
                progress.putResult("level_now", String.valueOf(player.experienceLevel));
                bot.systemChat("Meditation complete: +" + gained
                        + " levels (now L" + player.experienceLevel + ")", "light_purple");
                return BehaviorResult.SUCCESS;
            }
        }
        return BehaviorResult.RUNNING;
    }

    @Override
    public String describeState() {
        return "Meditating (" + gained + "/" + target + " levels)";
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {
    }
}
