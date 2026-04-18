package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotPlayer;

import java.util.ArrayDeque;
import java.util.Deque;

public class ActionQueue {
    private final BotPlayer bot;
    private final Deque<BotAction> queue = new ArrayDeque<>();
    private BotAction current = null;

    public ActionQueue(BotPlayer bot) {
        this.bot = bot;
    }

    public void enqueue(BotAction action) {
        queue.addLast(action);
    }

    public void clear() {
        queue.clear();
        current = null;
    }

    public void tick() {
        if (current == null) {
            current = queue.pollFirst();
        }
        if (current != null) {
            boolean done = current.tick(bot);
            if (done) {
                current = null;
            }
        }
    }

    public String currentAction() {
        if (current != null) return current.describe();
        return "idle";
    }

    public int queueSize() {
        return queue.size() + (current != null ? 1 : 0);
    }
}
