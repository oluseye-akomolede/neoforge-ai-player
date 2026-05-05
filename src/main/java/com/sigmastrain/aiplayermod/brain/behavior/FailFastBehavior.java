package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;

public class FailFastBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();
    private final String reason;

    public FailFastBehavior(String reason) {
        this.reason = reason;
    }

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setFailureReason(reason);
        bot.systemChat(reason, "red");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        return BehaviorResult.FAILED;
    }

    @Override
    public String describeState() {
        return "Failed: " + reason;
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
