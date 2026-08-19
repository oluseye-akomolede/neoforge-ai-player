package com.sigmastrain.aiplayermod.brain;

public enum BehaviorResult {
    RUNNING,
    SUCCESS,
    FAILED,
    /** The behavior ended itself as cancelled — a distinct terminal outcome
     *  from FAILED; the bot resets to idle and the directive is marked CANCELLED. */
    CANCELLED
}
