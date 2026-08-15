package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.phys.Vec3;

/**
 * Cultivation — the bot holds still and channels for a bounded span.
 *
 * <p>This behavior produces NOTHING by itself: no XP (that's
 * {@link MeditateBehavior}), no items (that's {@link ChannelBehavior}). It is
 * the resource-free posture of a hive unit "at work", whose economic meaning
 * lives in hive-mod — a tick handler there detects a unit running CULTIVATE
 * and routes the unit's FE toward the owner's reservoir. Keeping this side FE
 * and XP agnostic is what lets the two mods keep their ledgers separate.
 *
 * <p>{@code count} = seconds to cultivate (default 30, hard-capped at 24
 * hours so "cultivate for two hours" lands intact). The behavior simply holds
 * for that long and reports COMPLETED; the real value is accrued externally
 * while it runs.
 */
public class CultivateBehavior implements Behavior {

    private static final int DEFAULT_SECONDS = 30;
    private static final int MAX_SECONDS = 86400;

    private final ProgressReport progress = new ProgressReport();
    private int durationTicks;
    private int ticks;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        ticks = 0;
        int c = directive.getCount();
        int seconds = c > 0 ? Math.min(c, MAX_SECONDS) : DEFAULT_SECONDS;
        durationTicks = seconds * 20;
        progress.setPhase("CULTIVATING");
        progress.logEvent("Cultivating for " + seconds + "s");
        bot.systemChat("Cultivating for " + seconds + "s...", "aqua");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();
        ticks++;

        if (ticks % 4 == 0) {
            level.sendParticles(ParticleTypes.ENCHANT,
                    pos.x, pos.y + 1.5, pos.z, 2, 0.5, 0.5, 0.5, 0.1);
        }

        if (ticks >= durationTicks) {
            progress.logEvent("Cultivation complete");
            progress.putResult("seconds", String.valueOf(durationTicks / 20));
            bot.systemChat("Cultivation complete", "aqua");
            return BehaviorResult.SUCCESS;
        }
        return BehaviorResult.RUNNING;
    }

    @Override
    public String describeState() {
        return "Cultivating (" + (ticks / 20) + "/" + (durationTicks / 20) + "s)";
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {
    }
}
