package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;

public class IdleBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("idle");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return BehaviorResult.RUNNING;
    }

    @Override
    public String describeState() {
        return "Standing by";
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {}
}
