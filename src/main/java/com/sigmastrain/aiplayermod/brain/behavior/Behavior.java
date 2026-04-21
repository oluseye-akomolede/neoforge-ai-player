package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;

public interface Behavior {
    void start(BotPlayer bot, Directive directive);
    BehaviorResult tick(BotPlayer bot);
    String describeState();
    ProgressReport getProgress();
    void stop();
}
