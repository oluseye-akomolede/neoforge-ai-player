package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;

public interface BotAction {
    /** Called each server tick. Return true when the action is complete. */
    boolean tick(BotPlayer bot);

    /** Human-readable description for status reporting. */
    String describe();
}
