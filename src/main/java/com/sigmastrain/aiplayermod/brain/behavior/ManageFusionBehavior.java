package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.AnchorManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.Fusion;
import com.sigmastrain.aiplayermod.brain.FusionControl;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.blockfusion.RegulatorRegistry;
import com.sigmastrain.aiplayermod.compat.blockfusion.Regulator;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.block.entity.BlockEntity;

/**
 * The continuous "fused" directive. It runs forever (RUNNING) while the bot is
 * fused; each tick it re-reads {@link FusionControl} knobs so L3 commands change
 * its behavior live without cancelling it, and — for a reactor — runs the matched
 * {@link Regulator} to keep the device safe at the target rate. It is
 * economy-agnostic: hive's engine reads the fusion and does the FE. If the
 * fusion is cleared (unfuse, or the block is gone), it ends.
 */
public class ManageFusionBehavior implements Behavior {

    private final ProgressReport progress = new ProgressReport();
    private String botName;
    private int ticks;
    private BotPlayer lastBot;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        lastBot = bot;
        botName = bot.getPlayer().getGameProfile().getName();
        ticks = 0;
        Fusion.State st = Fusion.of(botName);
        progress.setPhase(st == null ? "not fused" : "managing " + st.role().name().toLowerCase());
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        Fusion.State st = Fusion.of(botName);
        if (st == null) return BehaviorResult.SUCCESS;   // unfused elsewhere

        ServerPlayer p = bot.getPlayer();
        if (!(p.level() instanceof ServerLevel level) || !level.dimension().location().toString().equals(st.dimension())) {
            // Bot left the block's dimension — pin it back onto the block.
            return BehaviorResult.RUNNING;
        }
        BlockPos pos = st.pos();
        if (!com.sigmastrain.aiplayermod.compat.blockfusion.BlockFusionCompat.isEnergyBlock(level, pos)) {
            bot.systemChat("Fusion lost — the block is gone", "yellow");
            endFusion(bot);
            return BehaviorResult.SUCCESS;
        }
        // Keep the bot on the block + hidden.
        if (++ticks % 20 == 0) {
            bot.teleport(pos.getX() + 0.5, pos.getY() + 1.0, pos.getZ() + 0.5);
            bot.setFusedInvisible(true);
        }

        // Reactor regulation (live knobs).
        Regulator reg = RegulatorRegistry.regulatorFor(level, pos);
        if (reg != null) {
            BlockEntity be = level.getBlockEntity(pos);
            if (be != null) {
                try {
                    reg.regulate(be, FusionControl.get(botName));
                    if (ticks % 40 == 0) progress.setPhase("reactor " + reg.read(be).state().toLowerCase());
                } catch (Exception ignored) {
                }
            }
        }
        return BehaviorResult.RUNNING;
    }

    private void endFusion(BotPlayer bot) {
        Fusion.unfuse(botName);
        FusionControl.clear(botName);
        AnchorManager.disable(bot);
        bot.setFusedInvisible(false);
    }

    @Override public String describeState() {
        Fusion.State st = Fusion.of(botName);
        return st == null ? "Not fused" : "Fused: " + st.role().name().toLowerCase();
    }
    @Override public ProgressReport getProgress() { return progress; }
    @Override public void stop() {
        // Manual UNFUSE clears state itself; a stop() from being replaced by
        // another directive should NOT unfuse (the bot may re-enter MANAGE),
        // so only clean up if the fusion was already cleared. No-op here.
    }
}
