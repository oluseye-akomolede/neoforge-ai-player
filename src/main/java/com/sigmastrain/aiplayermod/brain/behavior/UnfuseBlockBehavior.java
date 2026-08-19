package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.AnchorManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.Fusion;
import com.sigmastrain.aiplayermod.brain.FusionControl;
import com.sigmastrain.aiplayermod.brain.ProgressReport;

/** Break a fusion: unbind, release the chunk anchor, become visible again. */
public class UnfuseBlockBehavior implements Behavior {

    private final ProgressReport progress = new ProgressReport();

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        String name = bot.getPlayer().getGameProfile().getName();
        Fusion.State st = Fusion.of(name);
        Fusion.unfuse(name);
        FusionControl.clear(name);
        AnchorManager.disable(bot);
        bot.setFusedInvisible(false);
        if (st == null) {
            bot.systemChat("Not fused with anything", "yellow");
        } else {
            progress.logEvent("Unfused");
            bot.systemChat("Unfused", "aqua");
        }
    }

    @Override public BehaviorResult tick(BotPlayer bot) { return BehaviorResult.SUCCESS; }
    @Override public String describeState() { return "Unfusing"; }
    @Override public ProgressReport getProgress() { return progress; }
    @Override public void stop() {}
}
